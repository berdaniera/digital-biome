from flask import Flask, request, jsonify, url_for, abort
from flask_pymongo import PyMongo
from flask_compress import Compress
from datetime import datetime
import config as cfg
from jose import jwt
import binascii
import os

app = Flask(__name__)
app.config['MONGO_DBNAME'] = cfg.MONGO_DBNAME
app.config['MONGO2_DBNAME'] = cfg.MONGO2_DBNAME
app.config['MAX_CONTENT_LENGTH'] = 500*1024*1024
mongo = PyMongo(app) # main
mongo2 = PyMongo(app, config_prefix='MONGO2') # data
Compress(app)

def fix_periods(xx, method):
    if type(xx) is list:
        if type(xx[0]) is dict:
            if method=="in":
                return [{k.replace(u'.',u'\u2024'):v for k,v in i.iteritems()} for i in xx]
            elif method=="out":
                return [{k.replace(u'\u2024',u'.'):v for k,v in i.iteritems()} for i in xx]
        else: # it is a list
            if method=="in":
                return [x.replace(u'.',u'\u2024',) for x in xx]
            elif method=="out":
                return [x.replace(u'\u2024',u'.') for x in xx]
    else:
        if method=="in":
            return xx.replace(u'.',u'\u2024',)
        elif method=="out":
            return xx.replace(u'\u2024',u'.')

def get_key():
    key = request.headers.get('Authorization',None)
    if key is not None:
        key = key.split(" ")[1]
    else:
        key = request.args.get('key',None)
    return key

@app.route('/v1')
@app.route('/')
def nothing_here():
    return jsonify("Nothing here... move along...")

@app.route('/v1/<account_id>',methods=['GET'])
def get_account(account_id):
    key = get_key()
    if key is None:
        # simple account authorization test
        user = mongo.db.users.find_one({'account_id':account_id})
        if user is None:
            abort(400)
        return jsonify("Account exists! Great work.")
    else:
        # add a check for authentication
        user = mongo.db.users.find_one({'account_id':account_id, 'key':key})
        if user is None:
            abort(400)
        return jsonify("Authentication success! Great work.")

@app.route('/v1/<account_id>/data', methods=['GET'])
def check_data(account_id):
    #key = request.headers.get('Authorization').split(" ")[1]
    key = get_key()
    user = mongo.db.users.find_one({'account_id':account_id, 'key':key})
    if user is None:
        abort(400)
    aa = mongo.db.datasets.find({'account_id':account_id})
    if key: # get keys where user is allowed
        aa = [a for a in aa if a['data_id'] in user['data_ids']]
    else: # only get public datasets
        aa = [a for a in aa if a['private']==False]
    droplist = [u'_id',u'account_id',u'private']
    [a.pop(x,None) for x in droplist for a in aa]
    if len(aa)==0:
        aa = "No data uploaded yet"
    return jsonify(datasets=aa)

@app.route('/v1/<account_id>/data', methods=['POST'])
def add_data(account_id):
    key = request.headers.get('Authorization').split(" ")[1]
    admin_user = mongo.db.users.find_one({'account_id':account_id, 'key':jwt.get_unverified_claims(key)['key'], 'confirmed':True})
    try:
        jwt.decode(key, admin_user['secret'])
    except:
        return jsonify(error="Your authorization token is invalid or expired.")
    data = request.json['data']
    rows = len(data)
    data_id = fix_periods(request.json['data_id'], "in") # this should already be done, but just for safety
    if rows == 0:
        return jsonify(error="No data was received so nothing was done.")
    if data_id in admin_user['data_ids']:
        return jsonify(error="This data id ("+data_id+") already exists for your account, please choose a different id.")
    if admin_user['free'] and admin_user['nrows']+rows > 10000:
        return jsonify(error="Adding "+str(rows)+" rows will exceed your free account storage limit (currently using "+str(admin_user['nrows'])+"/10000). To add this data you can either upgrade your account or delete some other data.")
    if request.json.get('private') == 'true':
        private = True # if private, only the admin key gets access until granted to other keys...
    else:
        private = False
    creation_date = datetime.utcnow()
    variables = request.json['variables']
    if any(u"." in v for v in variables):
        data = fix_periods(data, "in")
    metadata = request.json.get('metadata',None)
    data = mongo2.db[account_id].insert_one({'data_id':data_id, 'data':data})
    mongo.db.datasets.insert_one({'account_id': account_id,
        'data_id': data_id, 'rows': rows, 'variables': variables,
        'creation_date': creation_date, 'metadata': metadata, 'private': private})
    # update user access to include this data_id and increment the number of rows
    mongo.db.users.update_one({'_id': admin_user['_id']},{'$push': {'data_ids': data_id}, '$inc': {'nrows': rows}}, upsert=False)
    newurl = url_for('query_data',account_id=account_id, data_id=data_id, _external=True)
    return jsonify(result="success", data_id=data_id, url=newurl)

@app.route('/v1/<account_id>/data/<data_id>', methods=['GET'])
def query_data(account_id, data_id):
    # check credentials
    dataset = mongo.db.datasets.find_one({'account_id':account_id, 'data_id':data_id})
    if dataset['private']: # if private is true, check credentials
        key = get_key()
        if key is None:
            return jsonify(error="Please supply an api key.")
        user = mongo.db.users.find_one({'account_id':account_id, 'key':key})
        if user is None or data_id not in user['data_ids']:
            return jsonify(error="Your authorization key is invalid for this data.")
    data = mongo2.db[account_id].find_one({'data_id':data_id})
    dataout = data['data']
    if any(u"." in v for v in dataset['variables']):
        dataout = fix_periods(dataout, "out")
    metadata = dataset['metadata']
    return jsonify(data_id=data_id, data=dataout, metadata=metadata)

@app.route('/v1/<account_id>/data/<data_id>', methods=['PUT'])
def update_data(account_id, data_id):
    # if PUT, replace the data - requires admin
    return "Not ready yet"

@app.route('/v1/<account_id>/data/<data_id>', methods=['DELETE'])
def delete_data(account_id, data_id):
    #validate admin
    # if DELETE, delete the data - requires admin
    return "Not ready yet"

@app.route('/v1/<account_id>/keys', methods=['GET','POST'])
def manage_keys(account_id):
    # Check credentials, only admin can manage keys
    key = request.headers.get('Authorization').split(" ")[1]
    admin_user = mongo.db.users.find_one({'account_id':account_id, 'key':jwt.get_unverified_claims(key)['key'], 'confirmed':True})
    try:
        jwt.decode(key, admin_user['secret'])
    except:
        return jsonify(error="Your authorization token is invalid or expired.")
    if request.method == 'GET':
        au = mongo.db.users.find({'account_id':account_id}) # all datasets
        k = []
        [k.append(a) for a in au]
        droplist = [u'_id',u'name',u'email',u'password',u'account_id',u'confirmed',u'secret']
        [[a.pop(x,None) for x in droplist] for a in k] # keeps key, data_ids, add_date
        # print k
        return jsonify(keys=k)
    if request.method == 'POST':
        data_ids = request.json.get('data_id',[]) # if does not exist, will return empty list
        newkey = binascii.hexlify(os.urandom(10))
        creation_date = datetime.utcnow()
        mongo.db.users.insert_one({
            'account_id': account_id,
            'key': newkey,
            'data_ids': data_ids,
            'add_date': creation_date})
        return jsonify(key=newkey, data_ids=data_ids)

@app.route('/v1/<account_id>/keys/<key>', methods=['DELETE'])
def delete_key(account_id, key):
    # delete key
    return "Not ready yet"

if __name__=='__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
