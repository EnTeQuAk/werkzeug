from nose.tools import assert_raises
from werkzeug.datastructures import ResponseCacheControl
from werkzeug.http import parse_cache_control_header
from werkzeug.test import Client, create_environ
from werkzeug.wrappers import Request, Response
from werkzeug.contrib import fixers


@Request.application
def path_check_app(request):
    return Response('PATH_INFO: %s\nSCRIPT_NAME: %s' % (
        request.environ.get('PATH_INFO', ''),
        request.environ.get('SCRIPT_NAME', '')
    ))


def test_lighttpd_cgi_root_fix():
    """Test the LighttpdCGIRootFix fixer"""
    app = fixers.LighttpdCGIRootFix(path_check_app)
    response = Response.from_app(app, dict(create_environ(),
        SCRIPT_NAME='/foo',
        PATH_INFO='/bar'
    ))
    assert response.data == 'PATH_INFO: /foo/bar\nSCRIPT_NAME: '


def test_path_info_from_request_uri_fix():
    """Test the PathInfoFromRequestUriFix fixer"""
    app = fixers.PathInfoFromRequestUriFix(path_check_app)
    for key in 'REQUEST_URI', 'REQUEST_URL', 'UNENCODED_URL':
        env = dict(create_environ(), SCRIPT_NAME='/test', PATH_INFO='/?????')
        env[key] = '/test/foo%25bar?drop=this'
        response = Response.from_app(app, env)
        assert response.data == 'PATH_INFO: /foo%bar\nSCRIPT_NAME: /test'


def test_proxy_fix():
    """Test the ProxyFix fixer"""
    @fixers.ProxyFix
    @Request.application
    def app(request):
        return Response('%s|%s' % (
            request.remote_addr,
            # do not use request.host as this fixes too :)
            request.environ['HTTP_HOST']
        ))
    response = Response.from_app(app, dict(create_environ(),
        HTTP_X_FORWARDED_HOST='example.com',
        HTTP_X_FORWARDED_FOR='1.2.3.4, 5.6.7.8',
        REMOTE_ADDR='127.0.0.1',
        HTTP_HOST='fake'
    ))
    assert response.data == '1.2.3.4|example.com'


def test_header_rewriter_fix():
    """Test the HeaderRewriterFix fixer"""
    @Request.application
    def application(request):
        return Response("", headers=[
            ('X-Foo', 'bar')
        ])
    application = fixers.HeaderRewriterFix(application, ('X-Foo',), (('X-Bar', '42'),))
    response = Response.from_app(application, create_environ())
    assert response.headers['Content-Type'] == 'text/plain; charset=utf-8'
    assert 'X-Foo' not in response.headers
    assert response.headers['X-Bar'] == '42'


def test_ie_fixes():
    """Test IE fixes."""
    @fixers.InternetExplorerFix
    @Request.application
    def application(request):
        response = Response('binary data here', mimetype='application/vnd.ms-excel')
        response.headers['Vary'] = 'Cookie'
        response.headers['Content-Disposition'] = 'attachment; filename=foo.xls'
        return response

    c = Client(application, Response)
    response = c.get('/', headers=[
        ('User-Agent', 'Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0)')
    ])

    # IE gets no vary
    assert response.data == 'binary data here'
    assert 'vary' not in response.headers
    assert response.headers['content-disposition'] == 'attachment; filename=foo.xls'
    assert response.headers['content-type'] == 'application/vnd.ms-excel'

    # other browsers do
    c = Client(application, Response)
    response = c.get('/')
    assert response.data == 'binary data here'
    assert 'vary' in response.headers

    cc = ResponseCacheControl()
    cc.no_cache = True

    @fixers.InternetExplorerFix
    @Request.application
    def application(request):
        response = Response('binary data here', mimetype='application/vnd.ms-excel')
        response.headers['Pragma'] = ', '.join(pragma)
        response.headers['Cache-Control'] = cc.to_header()
        response.headers['Content-Disposition'] = 'attachment; filename=foo.xls'
        return response


    # IE has no pragma or cache control
    pragma = ('no-cache',)
    c = Client(application, Response)
    response = c.get('/', headers=[
        ('User-Agent', 'Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0)')
    ])
    assert response.data == 'binary data here'
    assert 'pragma' not in response.headers
    assert 'cache-control' not in response.headers
    assert response.headers['content-disposition'] == 'attachment; filename=foo.xls'

    # IE has simplified pragma
    pragma = ('no-cache', 'x-foo')
    cc.proxy_revalidate = True
    response = c.get('/', headers=[
        ('User-Agent', 'Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0)')
    ])
    assert response.data == 'binary data here'
    assert response.headers['pragma'] == 'x-foo'
    assert response.headers['cache-control'] == 'proxy-revalidate'
    assert response.headers['content-disposition'] == 'attachment; filename=foo.xls'

    # regular browsers get everything
    response = c.get('/')
    assert response.data == 'binary data here'
    assert response.headers['pragma'] == 'no-cache, x-foo'
    cc = parse_cache_control_header(response.headers['cache-control'],
                                    cls=ResponseCacheControl)
    assert cc.no_cache
    assert cc.proxy_revalidate
    assert response.headers['content-disposition'] == 'attachment; filename=foo.xls'
