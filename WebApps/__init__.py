from flask import Flask,render_template,request

app = Flask(__name__)

@app.route('/index')
def get_index():
    return ("Hello world")

@app.route('/user/<username>/')
def get_index_username(username):
    return ("Hello, "+username)

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


if __name__ == "__main__":
    app.run()
