from flask import Flask,render_template,request

# 当test调用 __init__.py 时，将构造函数的 name 参数传给 Flask 程序，Flask 用这个参数决定程序的根目录
# __name__ = (str) 'Webapps'
app = Flask(__name__)

# 路由： URL到函数的映射关系
# 用修饰器把函数注册为事件的处理程序
@app.route('/index')
# 视图函数
def get_index():
    return ("Hello world")

# Flask把动态部分作为参数传入函数
@app.route('/user/<username>/')
def get_index_username(username):
    return ("Hello, "+username)

# 支持int float 和 path（把 / 作为动态片段的一部分）
@app.route('/user/<int:userid>/')
def get_index_userid(userid):
    return ("Hello, you're the NO."+str(userid)+" visitor")

@app.route('/user/<path:userpath>/')
def get_index_userpath(userpath):
    return ("Hello, this is your path:"+str(userpath))

# 使用模板
@app.route('/login',methods=['GET'])
def get_login():
    return render_template('Login_Index.html')

@app.route('/login',methods=['POST'])
def post_login():
    username = request.form['username']
    password = request.form['password']
    if username =='admin' and password == 'password':
        return render_template('Login_Success.html',username=username)
    return render_template('Login_Index.html',message='Invalid User or Password',username=username)

# Flask从客户端收到请求时，要让视图函数能访问一些对象，才能处理请求
# 请求对象封装了客户端发送的HTTP请求
# 将请求对象作为参数传入视图函数会导致每个视图函数都在增加参数
# 使用上下文可以临时把某些对象变成全局可访问
# 实际上多线程中处理的request对象不同，Flask使用上下文让特定变量在一个线程中全局访问（创建线程池），而不干扰其他线程
@app.route('/request/agent/',methods=['GET'])
def get_request_agent():
    user_agent = request.headers.get('User-Agent')
    return ('Your browser is '+user_agent)


if __name__ == "__main__":
    app.run(host='0.0.0.0',port=31942)

