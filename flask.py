# -*- coding: utf-8 -*-
"""
    flask
    ~~~~~

    flask 0.2 版本源码注解

    A microframework based on Werkzeug.  It's extensively documented
    and follows best practice patterns.

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import with_statement
import os
import sys
import mimetypes
from datetime import datetime, timedelta

from itertools import chain
from jinja2 import Environment, PackageLoader, FileSystemLoader
from werkzeug.wrappers import Request as RequestBase, Response as ResponseBase
from werkzeug.local import LocalStack, LocalProxy
from werkzeug.test import create_environ
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.datastructures import ImmutableDict, Headers
from werkzeug.utils import cached_property
from werkzeug.wsgi import wrap_file
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException
from werkzeug.contrib.securecookie import SecureCookie

# try to load the best simplejson implementation available.  If JSON
# is not installed, we add a failing class.
json_available = True
try:
    import simplejson as json
except ImportError:
    try:
        import json
    except ImportError:
        json_available = False

# 这些从Werkzeug和Jinja2导入的辅助函数（utilities）没有在
# 模块内使用，而是直接作为外部接口开放
#from werkzeug import abort, redirect
from jinja2 import Markup, escape

# 优先使用pkg_resource，如果无法工作则使用cwd。
try:
    import pkg_resources
    pkg_resources.resource_stream
except (ImportError, AttributeError):
    pkg_resources = None


class Request(RequestBase):
    """Flask默认使用的请求对象，用来记住匹配的端点值（endpoint）和视图参数（view arguments）。

    这就是最终的flask.request对象。如果你想替换掉这个请求对象，可以子类化这个
    类，然后将你的子类赋值给flask.Flask.request_class。
    """
    '''
    0.2版本更新：增加了module和json
    '''
    endpoint = view_args = routing_exception = None

    @property
    def module(self):
        """The name of the current module"""
        if self.endpoint and '.' in self.endpoint:
            return self.endpoint.rsplit('.', 1)[0]

    @cached_property
    def json(self):
        """If the mimetype is `application/json` this will contain the
        parsed JSON data.
        """
        if __debug__:
            _assert_have_json()
        if self.mimetype == 'application/json':
            return json.loads(self.data)


class Response(ResponseBase):
    """The response object that is used by default in flask.  Works like the
    response object from Werkzeug but is set to have a HTML mimetype by
    default.  Quite often you don't have to create this object yourself because
    :meth:`~flask.Flask.make_response` will take care of that for you.

    If you want to replace the response object used you can subclass this and
    set :attr:`~flask.Flask.request_class` to your subclass.
    """
    default_mimetype = 'text/html'


class _RequestGlobals(object):
    pass
'''
0.2版本更新：添加Session
'''

class Session(SecureCookie):
    """Expands the session with support for switching between permanent
    and non-permanent sessions.
    """

    def _get_permanent(self):
        return self.get('_permanent', False)

    def _set_permanent(self, value):
        self['_permanent'] = bool(value)

    permanent = property(_get_permanent, _set_permanent)
    del _get_permanent, _set_permanent


class _NullSession(Session):
    """Class used to generate nicer error messages if sessions are not
    available.  Will still allow read-only access to the empty session
    but fail on setting.
    """

    def _fail(self, *args, **kwargs):
        raise RuntimeError('the session is unavailable because no secret '
                           'key was set.  Set the secret_key on the '
                           'application to something unique and secret')
    __setitem__ = __delitem__ = clear = pop = popitem = \
        update = setdefault = _fail
    del _fail


class _RequestContext(object):
    """请求上下文（request context）包含所有请求相关的信息。它会在请求进入时被创建，
    然后被推送到_request_ctx_stack，在请求结束时会被相应的移除。它会为提供的
    WSGI环境创建URL适配器（adapter）和请求对象。
    """
    # 会在flask.Flask.request_context和flask.Flask.test_requset_context方法中
    # 调用，以便生成请求上下文。
    def __init__(self, app, environ):
        self.app = app
        self.url_adapter = app.url_map.bind_to_environ(environ)
        self.request = app.request_class(environ)
        self.session = app.open_session(self.request)
        if self.session is None:
            self.session = _NullSession()
        self.g = _RequestGlobals()
        self.flashes = None

        try:
            self.request.endpoint, self.request.view_args = \
                self.url_adapter.match()
        except HTTPException as e:
            self.request.routing_exception = e

    def __enter__(self):
        _request_ctx_stack.push(self)  # 将当前请求上下文对象推送到_request_ctx_stack堆栈，这个堆栈在最后定义

    def __exit__(self, exc_type, exc_value, tb):
        # 在调试模式（debug mode）而且有异常发生时，不要移除（pop）请求堆栈。
        # 这将允许调试器（debugger）在交互式shell中仍然可以获取请求对象。
        if tb is None or not self.app.debug:
            _request_ctx_stack.pop()


def url_for(endpoint, **values):
    """根据给定的端点和提供的方法生成一个URL。

    对于目标端点未知的变量参数，将会作为查询参数附加在URL后面（生成查询字符串）。

    ==================== ======================= =============================
    Active Module        Target Endpoint         Target Function
    ==================== ======================= =============================
    `None`               ``'index'``             `index` of the application
    `None`               ``'.index'``            `index` of the application
    ``'admin'``          ``'index'``             `index` of the `admin` module
    any                  ``'.index'``            `index` of the application
    any                  ``'admin.index'``       `index` of the `admin` module
    ==================== ======================= =============================

    Variable arguments that are unknown to the target endpoint are appended
    to the generated URL as query arguments.

    For more information, head over to the :ref:`Quickstart <url-building>`.

    :param endpoint: the endpoint of the URL (name of the function)
    :param values: the variable arguments of the URL rule
    :param _external: if set to `True`, an absolute URL is generated.
    """
    ctx = _request_ctx_stack.top
    if '.' not in endpoint:
        mod = ctx.request.module
        if mod is not None:
            endpoint = mod + '.' + endpoint
    elif endpoint.startswith('.'):
        endpoint = endpoint[1:]
    external = values.pop('_external', False)
    return ctx.url_adapter.build(endpoint, values, force_external=external)

'''
0.2更新：增加模板
'''
def get_template_attribute(template_name, attribute):
    """Loads a macro (or variable) a template exports.  This can be used to
    invoke a macro from within Python code.  If you for example have a
    template named `_foo.html` with the following contents:

    .. sourcecode:: html+jinja

       {% macro hello(name) %}Hello {{ name }}!{% endmacro %}

    You can access this from Python code like this::

        hello = get_template_attribute('_foo.html', 'hello')
        return hello('World')

    .. versionadded:: 0.2

    :param template_name: the name of the template
    :param attribute: the name of the variable of macro to acccess
    """
    return getattr(current_app.jinja_env.get_template(template_name).module,
                   attribute)


def flash(message):
    """闪现（flash）一个消息到下一个请求。为了从session中移除闪现过的消息
    并将其显示给用户，你必须在模板中调用get_flashed_messages。

    :param message: 被闪现的消息。
    """
    session.setdefault('_flashes', []).append(message)


def get_flashed_messages():
    """从session里拉取（pull）所有要闪现的消息并返回它们。在同一个请求中对这个函数的
    进一步调用会返回同样的消息。
    """
    flashes = _request_ctx_stack.top.flashes
    if flashes is None:
        _request_ctx_stack.top.flashes = flashes = session.pop('_flashes', [])
    return flashes


'''
0.2更新：增加jsno
'''
def jsonify(*args, **kwargs):
    """Creates a :class:`~flask.Response` with the JSON representation of
    the given arguments with an `application/json` mimetype.  The arguments
    to this function are the same as to the :class:`dict` constructor.

    Example usage::

        @app.route('/_get_current_user')
        def get_current_user():
            return jsonify(username=g.user.username,
                           email=g.user.email,
                           id=g.user.id)

    This will send a JSON response like this to the browser::

        {
            "username": "admin",
            "email": "admin@localhost",
            "id": 42
        }

    This requires Python 2.6 or an installed version of simplejson.

    .. versionadded:: 0.2
    """
    if __debug__:
        _assert_have_json()
    return current_app.response_class(json.dumps(dict(*args, **kwargs),
        indent=None if request.is_xhr else 2), mimetype='application/json')

'''
0.2更新：增加send_file
'''
def send_file(filename_or_fp, mimetype=None, as_attachment=False,
              attachment_filename=None):
    """Sends the contents of a file to the client.  This will use the
    most efficient method available and configured.  By default it will
    try to use the WSGI server's file_wrapper support.  Alternatively
    you can set the application's :attr:`~Flask.use_x_sendfile` attribute
    to ``True`` to directly emit an `X-Sendfile` header.  This however
    requires support of the underlying webserver for `X-Sendfile`.

    By default it will try to guess the mimetype for you, but you can
    also explicitly provide one.  For extra security you probably want
    to sent certain files as attachment (HTML for instance).

    Please never pass filenames to this function from user sources without
    checking them first.  Something like this is usually sufficient to
    avoid security problems::

        if '..' in filename or filename.startswith('/'):
            abort(404)

    .. versionadded:: 0.2

    :param filename_or_fp: the filename of the file to send.  This is
                           relative to the :attr:`~Flask.root_path` if a
                           relative path is specified.
                           Alternatively a file object might be provided
                           in which case `X-Sendfile` might not work and
                           fall back to the traditional method.
    :param mimetype: the mimetype of the file if provided, otherwise
                     auto detection happens.
    :param as_attachment: set to `True` if you want to send this file with
                          a ``Content-Disposition: attachment`` header.
    :param attachment_filename: the filename for the attachment if it
                                differs from the file's filename.
    """
    if isinstance(filename_or_fp, str):
        filename = filename_or_fp
        file = None
    else:
        file = filename_or_fp
        filename = getattr(file, 'name', None)
    if filename is not None:
        filename = os.path.join(current_app.root_path, filename)
    if mimetype is None and (filename or attachment_filename):
        mimetype = mimetypes.guess_type(filename or attachment_filename)[0]
    if mimetype is None:
        mimetype = 'application/octet-stream'

    headers = Headers()
    if as_attachment:
        if attachment_filename is None:
            if filename is None:
                raise TypeError('filename unavailable, required for '
                                'sending as attachment')
            attachment_filename = os.path.basename(filename)
        headers.add('Content-Disposition', 'attachment',
                    filename=attachment_filename)

    if current_app.use_x_sendfile and filename:
        if file is not None:
            file.close()
        headers['X-Sendfile'] = filename
        data = None
    else:
        if file is None:
            file = open(filename, 'rb')
        data = wrap_file(request.environ, file)

    return Response(data, mimetype=mimetype, headers=headers,
                    direct_passthrough=True)


def render_template(template_name, **context):
    """使用给定的上下文从模板（template）文件夹渲染一个模板。

    :param template_name: 要被渲染的模板文件名。
    :param context: 在模板上下文中应该可用（available）的变量。
    """
    current_app.update_template_context(context)
    return current_app.jinja_env.get_template(template_name).render(context)


def render_template_string(source, **context):
    """使用给定的模板源代码字符串（source string）和上下文渲染一个模板。

    :param template_name: 要被渲染的模板源代码。
    :param context: 在模板上下文中应该可用的变量。
    """
    current_app.update_template_context(context)
    return current_app.jinja_env.from_string(source).render(context)


def _default_template_ctx_processor():
    """默认的模板上下文处理器（processor）。注入request、session和g。"""
    # 把request、session和g注入到模板上下文，以便可以直接在模板中使用这些变量。
    reqctx = _request_ctx_stack.top
    return dict(
        request=reqctx.request,
        session=reqctx.session,
        g=reqctx.g
    )


'''
0.2 更新：json断言
'''
def _assert_have_json():
    """Helper function that fails if JSON is unavailable."""
    if not json_available:
        raise RuntimeError('simplejson not installed')


def _get_package_path(name):
    """返回包的路径，如果找不到则返回当前工作目录（cwd）。"""
    try:
        return os.path.abspath(os.path.dirname(sys.modules[name].__file__))
    except (KeyError, AttributeError):
        return os.getcwd()

'''
0.2更新:增加json
'''
# figure out if simplejson escapes slashes.  This behaviour was changed
# from one version to another without reason.
if not json_available or '\\/' not in json.dumps('/'):

    def _tojson_filter(*args, **kwargs):
        if __debug__:
            _assert_have_json()
        return json.dumps(*args, **kwargs).replace('/', '\\/')
else:
    _tojson_filter = json.dumps

'''
0.2更新：增加package
'''

class _PackageBoundObject(object):

    def __init__(self, import_name):
        #: the name of the package or module.  Do not change this once
        #: it was set by the constructor.
        self.import_name = import_name

        #: where is the app root located?
        self.root_path = _get_package_path(self.import_name)

    def open_resource(self, resource):
        """Opens a resource from the application's resource folder.  To see
        how this works, consider the following folder structure::

            /myapplication.py
            /schemal.sql
            /static
                /style.css
            /template
                /layout.html
                /index.html

        If you want to open the `schema.sql` file you would do the
        following::

            with app.open_resource('schema.sql') as f:
                contents = f.read()
                do_something_with(contents)

        :param resource: the name of the resource.  To access resources within
                         subfolders use forward slashes as separator.
        """
        if pkg_resources is None:
            return open(os.path.join(self.root_path, resource), 'rb')
        return pkg_resources.resource_stream(self.import_name, resource)


class _ModuleSetupState(object):

    def __init__(self, app, url_prefix=None):
        self.app = app
        self.url_prefix = url_prefix

'''
0.2更新：增加module
'''

class Module(_PackageBoundObject):
    """Container object that enables pluggable applications.  A module can
    be used to organize larger applications.  They represent blueprints that,
    in combination with a :class:`Flask` object are used to create a large
    application.

    A module is like an application bound to an `import_name`.  Multiple
    modules can share the same import names, but in that case a `name` has
    to be provided to keep them apart.  If different import names are used,
    the rightmost part of the import name is used as name.

    Here an example structure for a larger appliation::

        /myapplication
            /__init__.py
            /views
                /__init__.py
                /admin.py
                /frontend.py

    The `myapplication/__init__.py` can look like this::

        from flask import Flask
        from myapplication.views.admin import admin
        from myapplication.views.frontend import frontend

        app = Flask(__name__)
        app.register_module(admin, url_prefix='/admin')
        app.register_module(frontend)

    And here an example view module (`myapplication/views/admin.py`)::

        from flask import Module

        admin = Module(__name__)

        @admin.route('/')
        def index():
            pass

        @admin.route('/login')
        def login():
            pass

    For a gentle introduction into modules, checkout the
    :ref:`working-with-modules` section.
    """

    def __init__(self, import_name, name=None, url_prefix=None):
        if name is None:
            assert '.' in import_name, 'name required if package name ' \
                'does not point to a submodule'
            name = import_name.rsplit('.', 1)[1]
        _PackageBoundObject.__init__(self, import_name)
        self.name = name
        self.url_prefix = url_prefix
        self._register_events = []

    def route(self, rule, **options):
        """Like :meth:`Flask.route` but for a module.  The endpoint for the
        :func:`url_for` function is prefixed with the name of the module.
        """
        def decorator(f):
            self.add_url_rule(rule, f.__name__, f, **options)
            return f
        return decorator

    def add_url_rule(self, rule, endpoint, view_func=None, **options):
        """Like :meth:`Flask.add_url_rule` but for a module.  The endpoint for
        the :func:`url_for` function is prefixed with the name of the module.
        """
        def register_rule(state):
            the_rule = rule
            if state.url_prefix:
                the_rule = state.url_prefix + rule
            state.app.add_url_rule(the_rule, '%s.%s' % (self.name, endpoint),
                                   view_func, **options)
        self._record(register_rule)

    def before_request(self, f):
        """Like :meth:`Flask.before_request` but for a module.  This function
        is only executed before each request that is handled by a function of
        that module.
        """
        self._record(lambda s: s.app.before_request_funcs
            .setdefault(self.name, []).append(f))
        return f

    def before_app_request(self, f):
        """Like :meth:`Flask.before_request`.  Such a function is executed
        before each request, even if outside of a module.
        """
        self._record(lambda s: s.app.before_request_funcs
            .setdefault(None, []).append(f))
        return f

    def after_request(self, f):
        """Like :meth:`Flask.after_request` but for a module.  This function
        is only executed after each request that is handled by a function of
        that module.
        """
        self._record(lambda s: s.app.after_request_funcs
            .setdefault(self.name, []).append(f))
        return f

    def after_app_request(self, f):
        """Like :meth:`Flask.after_request` but for a module.  Such a function
        is executed after each request, even if outside of the module.
        """
        self._record(lambda s: s.app.after_request_funcs
            .setdefault(None, []).append(f))
        return f

    def context_processor(self, f):
        """Like :meth:`Flask.context_processor` but for a modul.  This
        function is only executed for requests handled by a module.
        """
        self._record(lambda s: s.app.template_context_processors
            .setdefault(self.name, []).append(f))
        return f

    def app_context_processor(self, f):
        """Like :meth:`Flask.context_processor` but for a module.  Such a
        function is executed each request, even if outside of the module.
        """
        self._record(lambda s: s.app.template_context_processors
            .setdefault(None, []).append(f))
        return f

    def _record(self, func):
        self._register_events.append(func)


class Flask(_PackageBoundObject):
    """The flask object implements a WSGI application and acts as the central
    object.  It is passed the name of the module or package of the
    application.  Once it is created it will act as a central registry for
    the view functions, the URL rules, template configuration and much more.

    The name of the package is used to resolve resources from inside the
    package or the folder the module is contained in depending on if the
    package parameter resolves to an actual python package (a folder with
    an `__init__.py` file inside) or a standard module (just a `.py` file).

    For more information about resource loading, see :func:`open_resource`.

    Usually you create a :class:`Flask` instance in your main module or
    in the `__init__.py` file of your package like this::

        from flask import Flask
        app = Flask(__name__)
    """

    #: the class that is used for request objects.  See :class:`~flask.request`
    #: for more information.
    request_class = Request

    #: 用作响应对象的类。更多信息参见flask.Response。
    response_class = Response

    #: 静态文件的路径。如果你不想使用静态文件，可以将这个值设为None，这样不会添加
    #: 相应的URL规则，而且开发服务器将不再提供（serve）任何静态文件。
    static_path = '/static'

    #: 如果设置了密钥（secret key），加密组件可以使用它来为
    #: cookies或其他东西签名。比如，当你想使用安全的cookie时，把它设为一个复杂的随机值。
    secret_key = None

    #: 安全cookie使用这个值作为session cookie的名称。
    session_cookie_name = 'session'  # 存储session对象数据的cookie名称

    #: A :class:`~datetime.timedelta` which is used to set the expiration
    #: date of a permanent session.  The default is 31 days which makes a
    #: permanent session survive for roughly one month.
    permanent_session_lifetime = timedelta(days=31)

    #: Enable this if you want to use the X-Sendfile feature.  Keep in
    #: mind that the server has to support this.  This only affects files
    #: sent with the :func:`send_file` method.
    #:
    #: .. versionadded:: 0.2
    use_x_sendfile = False

    #: options that are passed directly to the Jinja2 environment
    jinja_options = ImmutableDict(
        autoescape=True,
        extensions=['jinja2.ext.autoescape', 'jinja2.ext.with_']
    )

    def __init__(self, import_name):
        _PackageBoundObject.__init__(self, import_name)

        #: the debug flag.  Set this to `True` to enable debugging of
        #: the application.  In debug mode the debugger will kick in
        #: when an unhandled exception ocurrs and the integrated server
        #: will automatically reload the application if changes in the
        #: code are detected.
        self.debug = False

        #: a dictionary of all view functions registered.  The keys will
        #: be function names which are also used to generate URLs and
        #: the values are the function objects themselves.
        #: to register a view function, use the :meth:`route` decorator.
        self.view_functions = {}

        #: 一个储存所有已注册的错误处理器的字典。字段的键是整型（integer）类型的
        #: 错误码，字典的值是处理对应错误的函数。
        #: 要注册一个错误处理器，使用errorhandler装饰器。
        self.error_handlers = {}

        #: 一个应该在请求开始进入时、请求分发开始前调用的函数列表。举例来说，
        #: 这可以用来打开数据库连接或获取当前登录的用户。
        #: 要注册一个函数到这里，使用before_request装饰器。
        self.before_request_funcs = []

        #: 一个应该在请求处理结束时调用的函数列表。这些函数会被传入当前的响应
        #: 对象，你可以在函数内修改或替换它。
        #: 要注册一个函数到这里，使用after_request装饰器。
        self.after_request_funcs = []

        #: a dictionary with list of functions that are called without argument
        #: to populate the template context.  They key of the dictionary is the
        #: name of the module this function is active for, `None` for all
        #: requests.  Each returns a dictionary that the template context is
        #: updated with.  To register a function here, use the
        #: :meth:`context_processor` decorator.
        self.template_context_processors = {
            None: [_default_template_ctx_processor]
        }

        #: the :class:`~werkzeug.routing.Map` for this instance.  You can use
        #: this to change the routing converters after the class was created
        #: but before any routes are connected.  Example::
        #:
        #:    from werkzeug import BaseConverter
        #:
        #:    class ListConverter(BaseConverter):
        #:        def to_python(self, value):
        #:            return value.split(',')
        #:        def to_url(self, values):
        #:            return ','.join(BaseConverter.to_url(value)
        #:                            for value in values)
        #:
        #:    app = Flask(__name__)
        #:    app.url_map.converters['list'] = ListConverter
        self.url_map = Map()

        if self.static_path is not None:
            self.add_url_rule(self.static_path + '/<filename>',
                              build_only=True, endpoint='static')
            if pkg_resources is not None:
                target = (self.import_name, 'static')
            else:
                target = os.path.join(self.root_path, 'static')
            self.wsgi_app = SharedDataMiddleware(self.wsgi_app, {  # SharedDataMiddleware中间件用来为程序添加处理静态文件的能力
                self.static_path: target  # URL路径和实际文件目录（static文件夹）的映射
            })

        #: Jinja2环境。它通过jinja_options创建，加载器（loader）通过
        #: create_jinja_loader函数返回。
        self.jinja_env = Environment(loader=self.create_jinja_loader(),
                                     **self.jinja_options)
        self.jinja_env.globals.update(  # 将url_for和get_flashed_messages函数作为全局对象注入到模板上下文，以便在模板中调用
            url_for=url_for,
            get_flashed_messages=get_flashed_messages
        )
        self.jinja_env.filters['tojson'] = _tojson_filter

    def create_jinja_loader(self):
        """创建Jinja加载器。默认只是返回一个对应配置好的包的包加载器，它会从
        templates文件夹中寻找模板。要添加其他加载器，可以重载这个方法。
        """
        if pkg_resources is None:
            return FileSystemLoader(os.path.join(self.root_path, 'templates'))
        return PackageLoader(self.import_name)

    def update_template_context(self, context):
        """使用常用的变量更新模板上下文。这会注入request、session和g到模板上下文中。

        :param context: 包含额外添加的变量的字典，用来更新上下文。
        """
        funcs = self.template_context_processors[None]
        mod = _request_ctx_stack.top.request.module
        if mod is not None and mod in self.template_context_processors:
            funcs = chain(funcs, self.template_context_processors[mod])
        for func in funcs:
            context.update(func())

    def run(self, host='127.0.0.1', port=5000, **options):
        """Runs the application on a local development server.  If the
        :attr:`debug` flag is set the server will automatically reload
        for code changes and show a debugger in case an exception happened.

        :param host: the hostname to listen on.  set this to ``'0.0.0.0'``
                     to have the server available externally as well.
        :param port: the port of the webserver
        :param options: the options to be forwarded to the underlying
                        Werkzeug server.  See :func:`werkzeug.run_simple`
                        for more information.
        """
        from werkzeug.serving import run_simple
        if 'debug' in options:
            self.debug = options.pop('debug')
        options.setdefault('use_reloader', self.debug)  # 如果debug为True，开启重载器（reloader）
        options.setdefault('use_debugger', self.debug)  # 如果debug为True，开启调试器（debugger）
        return run_simple(host, port, self, **options)

    def test_client(self):
        """为这个程序创建一个测试客户端。"""
        from werkzeug.test import Client
        return Client(self, self.response_class, use_cookies=True)

    def open_session(self, request):
        """创建或打开一个新的session。默认的实现是存储所有的用户会话（session）
        数据到一个签名的cookie中。这需要secret_key属性被设置。

        :param request: request_class的实例。
        """
        key = self.secret_key
        if key is not None:
            return Session.load_cookie(request, self.session_cookie_name,
                                       secret_key=key)

    def save_session(self, session, response):
        """Saves the session if it needs updates.  For the default
        implementation, check :meth:`open_session`.

        :param session: the session to be saved (a
                        :class:`~werkzeug.contrib.securecookie.SecureCookie`
                        object)
        :param response: an instance of :attr:`response_class`
        """
        expires = None
        if session.permanent:
            expires = datetime.utcnow() + self.permanent_session_lifetime
        session.save_cookie(response, self.session_cookie_name,
                            expires=expires, httponly=True)

    def register_module(self, module, **options):
        """Registers a module with this application.  The keyword argument
        of this function are the same as the ones for the constructor of the
        :class:`Module` class and will override the values of the module if
        provided.
        """
        options.setdefault('url_prefix', module.url_prefix)
        state = _ModuleSetupState(self, **options)
        for func in module._register_events:
            func(state)

    def add_url_rule(self, rule, endpoint=None, view_func=None, **options):
        """Connects a URL rule.  Works exactly like the :meth:`route`
        decorator.  If a view_func is provided it will be registered with the
        endpoint.

        Basically this example::

            @app.route('/')
            def index():
                pass

        Is equivalent to the following::

            def index():
                pass
            app.add_url_rule('/', 'index', index)

        If the view_func is not provided you will need to connect the endpoint
        to a view function like so::

            app.view_functions['index'] = index

        .. versionchanged:: 0.2
           `view_func` parameter added.

        :param rule: the URL rule as string
        :param endpoint: the endpoint for the registered URL rule.  Flask
                         itself assumes the name of the view function as
                         endpoint
        :param view_func: the function to call when serving a request to the
                          provided endpoint
        :param options: the options to be forwarded to the underlying
                        :class:`~werkzeug.routing.Rule` object
        """
        if endpoint is None:
            assert view_func is not None, 'expected view func if endpoint ' \
                                          'is not provided.'
            endpoint = view_func.__name__
        options['endpoint'] = endpoint
        options.setdefault('methods', ('GET',))
        self.url_map.add(Rule(rule, **options))
        if view_func is not None:
            self.view_functions[endpoint] = view_func

    def route(self, rule, **options):
        """一个用于为给定的URL规则注册视图函数的装饰器。示例：

            @app.route('/')
            def index():
                return 'Hello World'

        路由中的变量部分可以使用尖括号来指定（/user/<username>）。默认情况下，
        URL中的变量部分接受任意不包含斜线的字符串，你也可以使用<converter:name>
        的形式来指定一个不同的转换器。

        变量部分将被作为关键字参数传入视图函数。

        可用的转换器如下所示：

        =========== ===========================================
        `int`       accepts integers
        `float`     like `int` but for floating point values
        `path`      like the default but also accepts slashes
        =========== ===========================================

        下面是一些示例：

            @app.route('/')
            def index():
                pass

            @app.route('/<username>')
            def show_user(username):
                pass

            @app.route('/post/<int:post_id>')
            def show_post(post_id):
                pass

        一个重要的细节是留意Flask是如何处理斜线的。为了让每一个URL独一无二，
        下面的规则被应用：

        1. 如果一个规则以一个斜线结尾而用户请求的地址不包含斜线，那么该用户
        会被重定向到相同的页面并附加一个结尾斜线。
        2. 如果一个规则没有以斜线结尾而用户请求的页面包含了一个结尾斜线，
        会抛出一个404错误。

        这和Web服务器处理静态文件的方式相一致。这也可以让你安全的使用相对链接目标。

        这个route装饰器也接受一系列参数：

        :param rule: 字符串形式的URL规则
        :param methods: 一个方法列表，可用的值限定为（GET、POST等）。默认一个
                        规则仅监听GET（以及隐式的HEAD）
        :param subdomain: 当子域名匹配使用时，为规则指定子域。
        :param strict_slashes: 可以用来为这个规则关闭严格的斜线设置，见上。
        :param options: 转发到底层的werkzeug.routing.Rule对象的其他选项。
        """
        def decorator(f):
            self.add_url_rule(rule, None, f, **options)
            return f
        return decorator

    def errorhandler(self, code):
        """一个用于为给定的错误码注册函数的装饰器。示例：

            @app.errorhandler(404)
            def page_not_found():
                return 'This page does not exist', 404

        你也可以不使用errorhandler注册一个函数作为错误处理器。下面的例子同上：

            def page_not_found():
                return 'This page does not exist', 404
            app.error_handlers[404] = page_not_found

        :param code: 对应处理器的整型类型的错误代码。
        """
        def decorator(f):
            self.error_handlers[code] = f
            return f
        return decorator

    def template_filter(self, name=None):
        """A decorator that is used to register custom template filter.
        You can specify a name for the filter, otherwise the function
        name will be used. Example::

          @app.template_filter()
          def reverse(s):
              return s[::-1]

        :param name: the optional name of the filter, otherwise the
                     function name will be used.
        """
        def decorator(f):
            self.jinja_env.filters[name or f.__name__] = f
            return f
        return decorator

    def before_request(self, f):
        """Registers a function to run before each request."""
        self.before_request_funcs.setdefault(None, []).append(f)
        return f

    def after_request(self, f):
        """Register a function to be run after each request."""
        self.after_request_funcs.setdefault(None, []).append(f)
        return f

    def context_processor(self, f):
        """Registers a template context processor function."""
        self.template_context_processors[None].append(f)
        return f

    #################################
    # 下面的几个方法用于处理请求和响应
    #################################

    def dispatch_request(self):
        """附注请求分发工作。匹配URL，返回视图函数或错误处理器的返回值。这个返回值
        不一定得是响应对象。为了将返回值返回值转换成合适的想要对象，调用make_response。
        """
        req = _request_ctx_stack.top.request
        try:
            if req.routing_exception is not None:
                raise req.routing_exception
            return self.view_functions[req.endpoint](**req.view_args)
        except HTTPException as e:
            handler = self.error_handlers.get(e.code)
            if handler is None:
                return e
            return handler(e)
        except Exception as e:
            handler = self.error_handlers.get(500)
            if self.debug or handler is None:
                raise
            return handler(e)

    def make_response(self, rv):
        """将视图函数的返回值转换成一个真正的响应对象，即response_class实例。

        rv允许的类型如下所示：

        ======================= ===========================================
        :attr:`response_class`  the object is returned unchanged
        :class:`str`            a response object is created with the
                                string as body
        :class:`unicode`        a response object is created with the
                                string encoded to utf-8 as body
        :class:`tuple`          the response object is created with the
                                contents of the tuple as arguments
        a WSGI function         the function is called as WSGI application
                                and buffered as response object
        ======================= ===========================================

        :param rv: 视图函数返回值
        """
        if rv is None:
            raise ValueError('View function did not return a response')
        if isinstance(rv, self.response_class):
            return rv
        if isinstance(rv, str):
            return self.response_class(rv)
        if isinstance(rv, tuple):
            return self.response_class(*rv)
        return self.response_class.force_type(rv, request.environ)

    def preprocess_request(self):
        """在实际的请求分发之前调用，而且将会调用每一个使用before_request
        装饰的函数。如果其中某一个函数返回一个值，这个值将会作为视图返回值
        处理并停止进一步的请求处理。
        """
        funcs = self.before_request_funcs.get(None, ())
        mod = request.module
        if mod and mod in self.before_request_funcs:
            funcs = chain(funcs, self.before_request_funcs[mod])
        for func in funcs:
            rv = func()
            if rv is not None:
                return rv

    def process_response(self, response):
        """为了在发送给WSGI服务器前修改响应对象，可以重写这个方法。 默认
        这会调用所有使用after_request装饰的函数。

        :param response: 一个response_class对象。
        :return: 一个新的响应对象或原对象，必须是response_class实例。
        """
        ctx = _request_ctx_stack.top
        mod = ctx.request.module
        if not isinstance(ctx.session, _NullSession):
            self.save_session(ctx.session, response)
        funcs = ()
        if mod and mod in self.after_request_funcs:
            funcs = chain(funcs, self.after_request_funcs[mod])
        if None in self.after_request_funcs:
            funcs = chain(funcs, self.after_request_funcs[None])
        for handler in funcs:
            response = handler(response)
        return response

    #########################################################################
    # WSGI规定的可调用对象，从请求进入，到生成响应并返回的整个处理流程都发生在这里
    #########################################################################

    def wsgi_app(self, environ, start_response):
        """The actual WSGI application.  This is not implemented in
        `__call__` so that middlewares can be applied without losing a
        reference to the class.  So instead of doing this::

            app = MyMiddleware(app)

        It's a better idea to do this instead::

            app.wsgi_app = MyMiddleware(app.wsgi_app)

        Then you still have the original application object around and
        can continue to call methods on it.

        :param environ: a WSGI environment
        :param start_response: a callable accepting a status code,
                               a list of headers and an optional
                               exception context to start the response
        """
        # 在with语句下执行相关操作，会触发_RequestContext中的__enter__方法，从而推送请求上下文到堆栈中
        with self.request_context(environ):
            rv = self.preprocess_request()  # 预处理请求，调用所有使用了before_request钩子的函数
            if rv is None:
                rv = self.dispatch_request  # 请求分发，获得视图函数返回值（或是错误处理器的返回值）
            response = self.make_response(rv)  # 生成响应，把上面的返回值转换成响应对象
            response = self.process_response(response)  # 响应处理，调用所有使用了after_request钩子的函数
            return response(environ, start_response)

    def request_context(self, environ):
        """从给定的环境创建一个请求上下文，并将其绑定到当前上下文。这必须搭配with
        语句使用，因为请求仅绑定在with块中的当前上下文里。

        用法示例：

            with app.request_context(environ):
                do_something_with(request)

        :param environ: 一个WSGI环境。
        """
        return _RequestContext(self, environ)

    def test_request_context(self, *args, **kwargs):
        """从给定的值创建一个WSGI环境（更多信息请参见werkzeug.create_environ，
        这个函数接受相同的参数）。
        """
        return self.request_context(create_environ(*args, **kwargs))

    def __call__(self, environ, start_response):
        """wsgi_app的快捷方式。"""
        return self.wsgi_app(environ, start_response)


# 本地上下文

# 请求上下文堆栈（_request_ctx_stack）栈顶（_request_ctx_stack.top）的对象即请求上下文对象（_RequestContext）实例
# 通过这里的调用可以获取当前请求上下文中保存的request、session等对象
# 请求上下文在wsgi_app方法中通过with语句调用request_context方法创建并推入堆栈

# 本地上下文相关的本地线程、本地堆栈和本地代理的实现这里不再展开，你需要先了解堆栈和代码在Python中的实现，
# 然后再通过阅读Werkzeug的文档或源码了解具体实现
# 另外，你也可以阅读《Flask Web开发实战》（helloflask.com/book）第16章16.4.3小节，这一小节首先介绍了本地线程和Werkzeug中实现的Local，
# 然后从堆栈和代理在Python中的基本实现开始，逐渐过渡到本地堆栈和本地代理的实现
_request_ctx_stack = LocalStack()
current_app = LocalProxy(lambda: _request_ctx_stack.top.app)
request = LocalProxy(lambda: _request_ctx_stack.top.request)
session = LocalProxy(lambda: _request_ctx_stack.top.session)
g = LocalProxy(lambda: _request_ctx_stack.top.g)
