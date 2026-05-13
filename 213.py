from flask import Flask

app = Flask(__name__)

if __name__ == '__main__':
    app.run(debug=True)
else:
    app.run(debug=False)