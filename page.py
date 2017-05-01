from flask import Flask, Markup, session, flash, render_template, request, jsonify, url_for, make_response, send_file, redirect, g
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail,  Message
from flask_pymongo import PyMongo
from datetime import datetime
import config as cfg
import binascii
import os

app = Flask(__name__)
app.config['MAIL_SERVER'] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 465
app.config["MAIL_USE_SSL"] = True
app.config["MAIL_USE_TLS"] = False
app.config["MAIL_DEFAULT_SENDER"] = ("Aaron from Digital Biome","aaron.berdanier@gmail.com")
app.config["MAIL_USERNAME"] = cfg.MAIL_USERNAME
app.config["MAIL_PASSWORD"] = cfg.MAIL_PASSWORD
app.config['SECRET_KEY'] = cfg.SECRET_KEY
app.config['SECURITY_PASSWORD_SALT'] = cfg.SECURITY_PASSWORD_SALT
app.config['MONGO_DBNAME'] = cfg.MONGO_DBNAME

mongo = PyMongo(app)
mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# users
# - {account_id, password, account_id, key, data_ids} # for regular users, omit password, automatically all data access
class User():
    def __init__(self, account_id):
        self.account_id = account_id
    def is_authenticated(self):
        return mongo.db.user.find_one({'account_id':self.account_id})['confirmed']
    def is_active(self):
        return True
    def is_anonymous(self):
        return False
    def get_id(self):
        return self.account_id

def validate_login(password_hash, password):
    return check_password_hash(password_hash, password)

def generate_confirmation_token(email):
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    return serializer.dumps(email, salt=app.config['SECURITY_PASSWORD_SALT'])

def confirm_token(token, expiration=3600*24): # expires in one day
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token,
            salt=app.config['SECURITY_PASSWORD_SALT'],
            max_age=expiration)
    except:
        return False
    return email

def send_email(to, subject, template):
    mail.send_message(subject, recipients=[to], html=template)

@login_manager.user_loader
def load_user(id):
    u = mongo.db.users.find_one({"account_id": id})
    if not u:
        return None
    return User(u['account_id'])

@app.before_request
def before_request():
    g.user = current_user

# index
@app.route('/',methods=['GET'])
@app.route('/index',methods=['GET'])
def index():
    return render_template('index.html')

# login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = mongo.db.users.find_one({'account_id': request.form['account_id']})
        if user:
            if validate_login(user['password'], request.form['password']):
                if user['confirmed']:
                    user_obj = User(user['account_id'])
                    login_user(user_obj)
                    flash("Logged in successfully", "alert-success")
                    return redirect(request.args.get("next") or url_for("admin"))
                else:
                    flash("Account not confirmed. Check your email.", "alert-warning")
        else:
            flash("Account id or password not recognized", 'alert-danger')
    return render_template('login.html')

# logout
@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# register
# - do stripe subscription
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        users = mongo.db.users
        # find either that account id or that email
        existing_user = users.find_one({"$or":[{'account_id':request.form['account_id']},{'email':request.form['email']}]})
        if existing_user is None: # account does not exist
            account_id = request.form['account_id']
            email = request.form['email']
            hashpass = generate_password_hash(request.form['password'])
            key = binascii.hexlify(os.urandom(6)) # random api key
            secret = binascii.hexlify(os.urandom(6)) # random secret key
            users.insert_one({
                'name': request.form['name'], 'email': email,
                'password': hashpass, 'account_id': account_id,
                'key': key, 'secret': secret, 'data_ids': [], 'nrows': 0,
                'confirmed': False, 'add_date': datetime.utcnow(), 'free': True})
            token = generate_confirmation_token(request.form['email'])
            register_url = url_for('complete_registration', token=token, _external=True)
            html = render_template('activatelink.html', confirm_url=register_url, account=account_id)
            subject = "Confirm your Digital Biome account"
            send_email(email, subject, html)
            flash('Check your email to confirm!', "alert-success")
            return redirect(url_for('login'))
        else: # otherwise, existing account...
            flash('An account already exists for this email or account name.', 'alert-danger')
    return render_template('register.html')

@app.route('/register/<token>', methods=['GET'])
def complete_registration(token):
    try:
        email = confirm_token(token)
        user = mongo.db.users.find_one_or_404({'email':email})
    except: # email is not confirmed or does not exist
        flash('The confirmation link is invalid or has expired.', 'alert-danger')
        return redirect(url_for('index'))
    if user['confirmed']:
        flash('Account already registered, please login.', "alert-success")
    else:
        mongo.db.users.update_one({'email':email},{'$set':{'confirmed':True}})
        flash('Registration complete, please login.', "alert-success")
    return redirect(url_for('login'))

# admin page
@app.route('/admin')
@login_required
def admin():
    admin_user = mongo.db.users.find_one({'account_id':current_user.account_id, 'confirmed':True})
    kk = mongo.db.users.find({'account_id': current_user.account_id}) # all datasets
    k = []
    [k.append(a) for a in kk if 'confirmed' not in a] # all the keys that are not admin
    droplist = [u'_id',u'name',u'email',u'password',u'account_id',u'confirmed',u'secret']
    [[a.pop(x,None) for x in droplist] for a in k] # keeps key, data_ids, add_date
    all_data = [str(a) for a in admin_user['data_ids']]
    key = admin_user['key']
    sec = admin_user['secret']
    return render_template('admin.html', keys=k, all_data=all_data, key=key, secret=sec)

# add key
@app.route('/_newkey', methods=['POST'])
@login_required
def newkey():
    data_ids = request.json['data_ids']
    newkey = binascii.hexlify(os.urandom(6))
    mongo.db.users.insert_one({
        'account_id': current_user.account_id,
        'key': newkey,
        'data_ids': data_ids,
        'add_date': datetime.utcnow()})
    return jsonify(result="success", key=newkey, data_ids=data_ids)

# edit key
@app.route('/_modkey', methods=['POST'])
@login_required
def modkey():
    key = request.json['key']
    data_ids = request.json['data_ids']
    mongo.db.users.update_one({'account_id':current_user.account_id, 'key':key},
        {'$set':{'data_ids':data_ids}})
    return jsonify(result="success")

# refresh key
@app.route('/_refkey', methods=['POST'])
@login_required
def refkey():
    key = request.json['key']
    newkey = binascii.hexlify(os.urandom(6))
    mongo.db.users.update_one({'account_id':current_user.account_id, 'key':key},
        {'$set':{'key':newkey}})
    return jsonify(result="success", key=newkey)

# delete key
@app.route('/_delkey', methods=['POST'])
@login_required
def delkey():
    key = request.json['key']
    mongo.db.users.delete_one({
        'account_id': current_user.account_id,
        'key': key})
    return jsonify(result='success')

if __name__=='__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
