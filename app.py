from flask import Flask, Markup, session, flash, render_template, request, jsonify, url_for, make_response, send_file, redirect, g
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer
from flask_pymongo import PyMongo
from sunrise_sunset import SunriseSunset as suns
from datetime import datetime, timedelta
import simplejson as json
import pandas as pd
import regex as re
import tempfile
import zipfile
import shutil
import os

app = Flask(__name__)
mongo = PyMongo(app)

############ FUNCTIONS
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1] in ['txt', 'dat', 'csv']

# save file to folder
def save_file(ff, collection, site):
    if ff and allowed_file(ff.filename):
        filename = secure_filename(ff.filename)
        fileup = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if ff.filename not in os.listdir(app.config['UPLOAD_FOLDER']):
            data = mongo.db[collection] # our data, create if doesn't exist
            ff.save(fileup)
            xx = pd.read_csv(fileup, parse_dates=[0])
            xx.rename(columns={xx.columns[0]:'datetime'}, inplace=True)
            xx['flag'] = None # add na column
            xx['site'] = site
            xx['datein'] = datetime.utcnow()
            datacolumns = xx.columns.tolist()
            jj = xx.to_dict(orient='records')
            collections = mongo.db.digitalbiome_collections # all collections
            collections.update_one({'collection':collection}, {'$addToSet':{'files':filename, 'sites':site, 'columns':{'$each':datacolumns}}})
            [data.update_one({'datetime':j['datetime']}, {'$set':j}, upsert=True) for j in jj]
            return {"Success":filename}
        else:
            return {"Existing":filename}
    else:
        return {"Failure":filename}

# get set up dictionaries
def get_setup(getall=True):
    collections = mongo.db.digitalbiome_collections # all collections
    allsites = [s['site'] for s in mongo.db.digitalbiome_sites.find()]
    projects = []
    sites = {}
    files = {}
    dates = {}
    columns = {}
    for c in collections.find():
        projects.append(c['collection'])
        sites[c['collection']] = c.get('sites',None) # project specific sites
        files[c['collection']] = c.get('files',None) # files in the database
        if getall and c['collection'] in mongo.db.collection_names():
            dd = mongo.db[c['collection']]
            dates[c['collection']] = [dd.find_one(sort=[('datetime',1)])['datetime'].strftime("%Y-%m-%dT%H:%M:%SZ"), dd.find_one(sort=[('datetime',-1)])['datetime'].strftime("%Y-%m-%dT%H:%M:%SZ")]
            columns[c['collection']] = [co for co in c['columns'] if co not in ['datetime','flag','site','datein']]
    return [projects, allsites, files, sites, dates, columns]

# get metadata
def get_metadata(project, sites):
    # note, sites is a list
    collections = mongo.db.digitalbiome_collections # all collections
    description = collections.find_one({'collection':project})['description']
    ss = mongo.db.digitalbiome_sites.find({'site':{'$in':sites}})
    sitedata = []
    [sitedata.append({k:v for k,v in s.items() if k in ['site','lat','lng','description']}) for s in ss]
    descdict = {'Title':project,
        'Creator':{'Name':'Aaron Berdanier','Email':'aaron.berdanier@gmail.com'},
        'Downloaded':datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        'Description':description,
        'Notes:':'All date-times are assumed to be in in UTC with ISO formatting (%Y-%m-%dT%H:%M:%SZ). Data managed by DigitalBiome.io.',
        'Sites':sitedata}
    return descdict

###########
@app.route('/')
@app.route('/index')
def index():
    return render_template('index.html')

# Admin stuff
@app.route('/admin', methods=['GET','POST'])
def admin():
    if request.method == 'POST':
        if request.form['formid']=="addproj":
            # strip punctuation, space to dash, string to lower
            project = re.sub(ur"\p{P}+","",request.form['project']).replace(" ","-").lower()
            collections = mongo.db.digitalbiome_collections # all collections
            cc = collections.find_one({'collection':project}) # our collection
            if cc:
                flash('Project already exists: '+project,'alert-danger')
            else:
                collections.insert_one({'collection':project,'columns':[],'sites':[],'files':[],'description':request.form['description']})
                flash('Added project: '+project,'alert-success')
        elif request.form['formid']=="addsite":
            # strip punctuation, space to dash, string to lower
            site = re.sub(ur"\p{P}+","",request.form['site']).replace(" ","-").lower()
            sites = mongo.db.digitalbiome_sites # all sites metadata
            ss = sites.find_one({'site':site}) # our site
            if ss:
                flash("Site data already exists","alert-danger")
            else:
                sites.insert_one({'site':site,'lat':request.form['lat'],'lng':request.form['lng'],'description':request.form['description']})
                flash('Added site: '+site,'alert-success')
    projects, allsites, files = get_setup(False)[:3]
    return render_template('admin.html', projects=projects, allsites=allsites, files=files)


@app.route('/archivefiles/<fname>')
def send_archived_file(fname):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], fname), as_attachment=True, attachment_filename=fname)


# UPLOAD stuff
@app.route('/upload', methods=['GET','POST'])
def upload():
    if request.method == 'POST':  # checks
        if 'file' not in request.files:
            flash('No file part','alert-danger')
            return redirect(request.url)
        ufiles = request.files.getlist("file") # files to upload
        collection = request.form['project'] # our collection name - from data selection
        site = request.form['site'] # our site name - from site selection
        filenames = [save_file(ff, collection, site) for ff in ufiles]
        return jsonify(result=filenames)
    else:
        projects, allsites = get_setup(False)[:2]
        return render_template('upload.html', projects=projects, allsites=allsites)

# Viz/clean stuff
@app.route('/graph')
def graph():
    projects, allsites, files, sites, dates, columns = get_setup()
    return render_template("graph.html", projects=projects, sites=sites, dates=dates, columns=columns)

@app.route('/_getviz',methods=["POST"])
def getviz():
    project = request.json['project']
    site = request.json['site']
    startdt = datetime.strptime(request.json['startDate']+" 00:00:00","%Y-%m-%d %H:%M:%S")
    enddt = datetime.strptime(request.json['endDate']+" 23:59:59","%Y-%m-%d %H:%M:%S")
    columns = request.json['columns']
    columns.append("datetime")
    dd = mongo.db[project]
    data = []
    for d in dd.find({'datetime':{'$gte':startdt,'$lt':enddt},'site':site}).sort([('site',1),('datetime',1)]):
        ii = {c:None if c not in d.keys() else d[c].strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(d[c],datetime) else d[c] for c in columns}
        data.append(ii)
    return jsonify(dat=data, variables=[c for c in columns if c!="datetime"])


@app.route('/clean')
def qaqc():
    flags = [''] # a list of flags
    for f in mongo.db.digitalbiome_flags.find(): flags.append(f['flag'])
    projects, allsites, files, sites, dates, columns = get_setup()
    return render_template("clean.html", projects=projects, sites=sites, dates=dates, columns=columns, flags=flags)

@app.route('/_getqaqc',methods=["POST"])
def getqaqc():
    project = request.json['project']
    site = request.json['site']
    cc = mongo.db.digitalbiome_collections.find_one({'collection':project}) # our columns
    columns = [c for c in cc['columns'] if c not in ['site','datein']]
    dd = mongo.db[project]
    data = []
    for d in dd.find({'site':site}).sort([('site',1),('datetime',1)]): # get data from site without NAs
        ii = {c:None if c not in d.keys() else d[c].strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(d[c],datetime) else d[c] for c in columns}
        data.append(ii)
    # get flag data, anywhere where data['flag'] is not None
    flagdata = [d['datetime'] for d in data if d['flag'] is not None] # datetimes of flag data
    map(lambda d: d.pop('flag'), data)
    # Get sunrise sunset data
    sdt = dd.find_one(sort=[('datetime',1)])['datetime'].replace(hour=0, minute=0,second=0,microsecond=0)
    edt = dd.find_one(sort=[('datetime',-1)])['datetime'].replace(hour=0, minute=0,second=0,microsecond=0)+timedelta(days=1)
    ddt = edt-sdt
    ss = mongo.db.digitalbiome_sites.find_one({'site':site})
    lat = float(ss['lat'])
    lng = float(ss['lng'])
    rss = []
    for i in range(ddt.days + 1):
        rise, sets = list(suns(sdt+timedelta(days=i-1), latitude=lat, longitude=lng).calculate())
        if rise>sets:
            sets = sets + timedelta(days=1) # account for UTC
        rss.append([rise, sets])
    #
    rss = pd.DataFrame(rss, columns=("rise","set"))
    rss.set = rss.set.shift(1)
    sunriseset = rss.loc[1:].to_json(orient='records',date_format='iso')
    # Get 4wk plot intervals
    def daterange(start, end):
        r = (end+timedelta(days=1)-start).days
        if r%28 > 0:
            r = r+28
        return [(end-timedelta(days=i)).strftime('%Y-%m-%d') for i in range(0,r,28)]
    drr = daterange(sdt,edt)
    variables = [c for c in columns if c not in ['datetime','flag']]
    return jsonify(dat=data, variables=variables, sunriseset=sunriseset, flagdat=flagdata, plotdates=drr)

@app.route('/_addflag',methods=["POST"])
def addflag():
    project = request.json['project']
    site = request.json['site']
    sdt = datetime.strptime(request.json['startDate'],"%Y-%m-%dT%H:%M:%S.%fZ")
    edt = datetime.strptime(request.json['endDate'],"%Y-%m-%dT%H:%M:%S.%fZ")
    flg = request.json['flagid']
    cmt = request.json['comment']
    flgid = mongo.db.digitalbiome_flags.insert_one({'flag':flg,'comment':cmt,'datein':datetime.utcnow()}) # add userid current_user.get_id()
    result = mongo.db[project].update_many({'site':site,'datetime':{'$gte':sdt,'$lt':edt}}, {'$set':{'flag':flgid.inserted_id}})
    return jsonify(result="success")

@app.route('/_addna',methods=["POST"])
def addna():
    project = request.json['project']
    site = request.json['site']
    var = request.json['var']
    sdt = datetime.strptime(request.json['startDate'],"%Y-%m-%dT%H:%M:%S.%fZ")
    edt = datetime.strptime(request.json['endDate'],"%Y-%m-%dT%H:%M:%S.%fZ")
    cc = mongo.db.digitalbiome_collections.find_one({'collection':project}) # our columns
    columns = [c for c in cc['columns'] if c not in ['site','datein','flag']]
    dd = mongo.db[project]
    dd.update_many({'site':site,'datetime':{'$gte':sdt,'$lt':edt}}, {'$unset':{var:1}}) # remove from document
    # new query to return data that is not NA for re plotting
    data = []
    for d in dd.find({'site':site}).sort([('site',1),('datetime',1)]):
        ii = {c:None if c not in d.keys() else d[c].strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(d[c],datetime) else d[c] for c in columns}
        data.append(ii)
    return jsonify(dat=data)

# Data download
@app.route('/download')
def download():
    projects, allsites, files, sites, dates, columns = get_setup()
    return render_template("download.html", projects=projects, sites=sites, dates=dates, columns=columns)

@app.route('/_getzip', methods=['POST'])
def getzip():
    tmp = tempfile.mkdtemp()
    project = request.form['project']
    sites = [request.form['site']]#.split(",")
    # get/write metadata
    descdict = get_metadata(project, sites)
    md = open(tmp+"/metadata.json","w")
    md.write(json.dumps(descdict,indent=4,sort_keys=False))
    md.close()
    # get/write data
    startdt = datetime.strptime(request.form['startDate']+" 00:00:00","%Y-%m-%d %H:%M:%S")
    enddt = datetime.strptime(request.form['endDate']+" 23:59:59","%Y-%m-%d %H:%M:%S")
    columns = request.form['variables'].split(",")
    data = []
    flags = mongo.db.digitalbiome_flags
    for d in mongo.db[project].find({'datetime':{'$gte':startdt,'$lt':enddt},'site':{'$in':sites}}).sort([('site',1),('datetime',1)]):
        if d['flag'] is not None: # get flag from db
            ff = flags.find_one({'_id':d['flag']})
            flag = ff['flag']
            comment = ff['comment']
        else:
            flag = comment = None
        ii = {'datetime':d['datetime'].strftime("%Y-%m-%dT%H:%M:%SZ"),'site':d['site'],'flag':flag,'comment':comment}
        for col in columns:
            if d.get(col,None): ii[col] = d[col]
        data.append(ii)
    # for d in dd.find({'datetime':{'$gte':startdt,'$lt':enddt},'site':{'$in':sites},'flag':{'$not':'NA'}}).sort([('site',1),('datetime',1)]):
    #     ii = {c:None if c not in d.keys() else d[c].strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(d[c],datetime) else d[c] for c in columns}
    #     data.append(ii)
    xx = pd.DataFrame.from_dict(data) # create dataframe from data
    cols = ['datetime','site']  + [col for col in xx if col not in ['datetime','site','flag','comment']] + ['flag','comment']
    xx[cols].to_csv(tmp+'/data.csv',index=False)
    # create/dowload zip file
    with zipfile.ZipFile(tmp+'/DBdownload.zip','w') as zf:
        [zf.write(tmp+"/"+f,f) for f in ['metadata.json','data.csv']]
    return send_file(tmp+'/DBdownload.zip', 'application/zip', as_attachment=True, attachment_filename="DBdownload.zip")

@app.route('/connect')
@app.route('/api/v1/')
def connect():
    return render_template("connect.html")

@app.route('/api/v1/<command>')
@app.route('/api/v1/<command>/<project>')
def api(command,project=None):
    collections = mongo.db.digitalbiome_collections # all collections
    # allsites = [s['site'] for s in mongo.db.digitalbiome_sites.find()]
    #project = request.args.get('project')
    if command == 'projects':
        #../api/v1/projects - get all projects listed {project:'asdf',sites:['a','b'],variables:['A','B','C'],start:'YYYY-mm-dd',end:'YYYY-mm-dd'}
        #../api/v1/sites?project= - list all sites by project
        #../api/v1/columns?project=&sites= - list all columns by project
        #../api/v1/dates?project=&sites=&columns= - list all dates by project {project:'asdf',start:'date',end:'date'}
        resp = []
        for c in collections.find():
            dd = mongo.db[c['collection']]
            end = dd.find_one(sort=[('datetime',-1)])['datetime'].strftime("%Y-%m-%d")
            start = dd.find_one(sort=[('datetime',1)])['datetime'].strftime("%Y-%m-%d")
            cc = {'project':c['collection']}
            cc['description'] = c['description']
            cc['attributes'] = {'sites':c['sites']}
            cc['attributes']['columns'] = [co for co in c['columns'] if co not in ['datetime','flag','site','datein']]
            cc['attributes']['dates'] = {'start':start,'end':end}
            resp.append(cc)
        return jsonify(projects=resp)
    elif command == 'sites':
        #../api/v1/sites/<project> - list all sites by project
        #query = {} if project is None else {'Site':collections.find_one({'collection':project})['sites']}
        query = {} if project is None else {'site':{'$in':collections.find_one({'collection':project})['sites']}}
        resp = []
        for s in mongo.db.digitalbiome_sites.find(query):
            ss = {'site':s['site'],'description':s['description'],'coordinates':[float(s['lng']),float(s['lat'])]}
            resp.append(ss)
        return jsonify(sites=resp)
    elif command == 'data':
        #../api/v1/data/<project>?sites=&columns=&start=&end=
        if project is None:
            return jsonify(error="Merging projects is not yet available through the API. Please enter a project...")
        else:
            query = {} #'flag':{'$not':re.compile('^NA$')}
            resp = []
            sites = request.args.get('sites')
            columns = request.args.get('columns')
            if columns is None: # get all columns
                allcols = mongo.db.digitalbiome_collections.find_one({'collection':project})['columns']
                columns = [co for co in allcols if co not in ['datetime','flag','site','datein']]
            else:
                columns = columns.split(",")
            start = request.args.get('start')
            end = request.args.get('end')
            if sites:
                query['site'] = {'$in':sites.split(",")}
            if start:
                query['datetime'] = {}
                query['datetime']['$gte'] = datetime.strptime(start+" 00:00:00","%Y-%m-%d %H:%M:%S")
            if end:
                if not start: query['datetime'] = {}
                query['datetime']['$lt'] = datetime.strptime(end+" 23:59:59","%Y-%m-%d %H:%M:%S")
            flags = mongo.db.digitalbiome_flags
            for d in mongo.db[project].find(query).sort([('site',1),('datetime',1)]):
                dd = {'datetime':d['datetime'].strftime("%Y-%m-%dT%H:%M:%SZ"),'site':d['site']}
                if d['flag'] is not None: # get flag from db
                    ff = flags.find_one({'_id':d['flag']})
                    dd['flag'] = ff['flag']
                    dd['comment'] = ff['comment']
                for col in columns:
                    if d.get(col,None): dd[col] = d[col]
                resp.append(dd)
            return jsonify(data=resp)
    else:
        # stuff - error
        return jsonify(error="Something went wrong that we hadn't anticipated...")

if __name__ == '__main__':
    app.run(debug=True)
