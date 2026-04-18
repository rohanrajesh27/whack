from flask import Flask, session, render_template, redirect, url_for, request, g

import sqlite3
import datetime
import random

app = Flask("app")
FLASK_ENV = "development"
app.secret_key = "CHANGE ME"


def get_connection():
    connection = getattr(g, "_database", None)
    if connection is None:
        connection = g._database = sqlite3.connect("database.db")
        connection.row_factory = sqlite3.Row
    return connection


@app.teardown_appcontext
def close_connection(exception):
    connection = getattr(g, "_database", None)
    if connection is not None:
        connection.close()


'''
TEMPLATE FOR CALLING THE DB

conn = get_connection()
cursor = conn.cursor()
cursor.execute("SQL QUERY")
data = cursor.fetchall()
row_1 = data[0]
cursor.close()

'''



@app.route('/')
def home():
    return render_template("home.html")

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)