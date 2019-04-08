from flask import Flask

app = Flask(__name__)

@app.route('/index')
def get_index():
    return ("Hello world")

@app.route('/user/<username>')
def get_index_username(username):
    return ("Hello, "+username)


if __name__ == "__main__":
    app.run()
