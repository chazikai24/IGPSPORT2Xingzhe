import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import requests, json
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import garth
import zipfile
import hashlib

def encrpt(password, public_key):
    rsa = RSA.importKey(public_key)
    cipher = PKCS1_v1_5.new(rsa)
    return base64.b64encode(cipher.encrypt(password.encode())).decode()

def syncData(username, password, garmin_email = None, garmin_password = None):
    headers = {
        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        "Accept-Encoding" : "gzip, deflate",
    }

    igp_host = "my.igpsport.com"
    if os.getenv("IGPSPORT_REGION") == "global":
        igp_host = "i.igpsport.com"

    session = requests.session()
    type = 1 #default igp

    if garmin_password is not None and garmin_password != '':
        type = 2 #garmin


    # login account
    if type == 2:
        print("同步佳明数据")

        garth.configure(domain="garmin.cn")
        garth.login(garmin_email, garmin_password)
        activities = garth.connectapi(
            f"/activitylist-service/activities/search/activities",
            params={"activityType": "cycling", "limit": 10, "start": 0, 'excludeChildren': False},
        )
    else:
        print("同步IGP数据")

        #url = "https://%s/Auth/Login" % igp_host
        url = "https://prod.zh.igpsport.com/service/auth/account/login"
        data = {
            'username': username,
            'password': password,
            'appId': 'igpsport-web'
        }
        headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/plain, */*',
                'Origin': 'https://app.zh.igpsport.com',
                'Referer': 'https://app.zh.igpsport.com/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'
            }
        res = requests.post(url, json=data, headers=headers, timeout=30)
        response_data = res.json()
        access_token = response_data['data']['access_token']

        # get igpsport list
        #url = "https://%s/Activity/ActivityList" % igp_host
        url = "https://prod.zh.igpsport.com/service/web-gateway/web-analyze/activity/queryMyActivity"
        params = {
                'pageNo': 1,
                'pageSize': 20,
                'reqType': 0,
                'sort': 1
            }
        headers = {
                    'Accept': 'application/json, text/plain, */*',
                    'Authorization': f'Bearer {access_token}',
                    'Origin': 'https://app.zh.igpsport.com',
                    'Referer': 'https://app.zh.igpsport.com/',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
                    'timezone': 'Asia/Shanghai',
                    'qiwu-app-version': '1.0.0'
                }
        res = requests.get(url,params=params, headers=headers, timeout=30)
        #result = json.loads(res.text, strict=False)
        result = res.json()
        activities = result.get('data', {}).get('rows', [])
        #result = json.loads(res.text)

    # login xingzhe account
    encrypter_public_key    = "-----BEGIN PUBLIC KEY-----\nMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDmuQkBbijudDAJgfffDeeIButq\nWHZvUwcRuvWdg89393FSdz3IJUHc0rgI/S3WuU8N0VePJLmVAZtCOK4qe4FY/eKm\nWpJmn7JfXB4HTMWjPVoyRZmSYjW4L8GrWmh51Qj7DwpTADadF3aq04o+s1b8LXJa\n8r6+TIqqL5WUHtRqmQIDAQAB\n-----END PUBLIC KEY-----\n"
    safe_password           = encrpt(password, encrypter_public_key)
    
    url     = "https://www.imxingzhe.com/api/v1/user/login/"
    data    = {
        'account': username, 
        'password': safe_password, 
    }
    res     = session.post(url, json=data, headers=headers)
    if res.status_code != 200:
        print("行者登录失败")
        return False
    result  = json.loads(res.text, strict=False)
    print("用户名:%s" % result['data']['username'])

    # get current month data
    #url     = "https://www.imxingzhe.com/api/v1/pgworkout/?offset=0&limit=10&sport=3&year=&month="
    #不限制骑行类型，sport=12为室内骑行
    url     = "https://www.imxingzhe.com/api/v1/pgworkout/?offset=0&limit=20&year=&month="
    res     = session.get(url, headers=headers)
    result  = json.loads(res.text, strict=False)
    data  = result["data"]["data"]

    sync_data = []
    # get not upload activity
    timezone = ZoneInfo('Asia/Shanghai')  # to Shanghai timezero in Gtihub Action env

    for activity in activities:
        if type == 2: #garmin
            dt        = datetime.strptime(activity["startTimeLocal"], "%Y-%m-%d %H:%M:%S")
            dt2       = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tzinfo=timezone)
            s_time    = dt2.timestamp()
            mk_time   = int(s_time) * 1000
        else:
            #dt        = datetime.strptime(activity["startTime"], "%Y-%m-%d %H:%M:%S")
            #dt2       = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tzinfo=timezone)
            #s_time    = dt2.timestamp()
            #mk_time   = int(s_time) * 1000
            #igp api返回的日期格式是 "YYYY.MM.DD"
            igp_date = activity["startTime"]
            #igp api返回的骑行距离取整
            igp_Distance = int(float(activity["rideDistance"]))
            #igp api返回的骑行时间取整
            igp_MovingTime = int(float(activity["totalMovingTime"]))

        need_sync = True

        for item in data:
            #将行者start_time时间戳转换为日期
            xz_date = (datetime.fromtimestamp(int(item["start_time"])/1000) + timedelta(hours=8)).strftime("%Y.%m.%d")
            #行者返回的骑行距离取整
            xz_Distance = int(float(item["distance"]))
            #行者返回的骑行时间(取样观察：sport=12的骑行台数据与igp不一致且无规律)
            xz_MovingTime = item["duration"]
            #sport=12的骑行台数据只比对骑行时间与距离
            if  item["sport"] == 12 :
                if xz_date == igp_date and xz_Distance == igp_Distance :
                    need_sync = False
                    break
            else:
                if xz_date == igp_date and xz_Distance == igp_Distance and xz_MovingTime == igp_MovingTime :
                    need_sync = False
                    break
        if need_sync:
            sync_data.append(activity)

    if len(sync_data) == 0:
        print("nothing data need sync")

    else:
        #down file
        upload_url = "https://www.imxingzhe.com/api/v1/fit/upload/"
        for sync_item in sync_data:
            if type == 2:  # garmin
                rid     = sync_item['activityId']
                rid = str(rid)
                print("sync rid:" + rid)
                res = garth.download(
                    f"/download-service/files/activity/{rid}",
                )
                with open(rid+".zip", "wb") as f:
                    f.write(res)
                with zipfile.ZipFile(rid+".zip", 'r') as zip_ref:
                    zip_ref.extractall(rid)
                with open(rid+"/"+rid+"_ACTIVITY.fit", 'rb') as fd:
                    data = fd.read()
                    result = session.post(upload_url, files={
                        "file_source": (None, "undefined", None),
                        "fit_filename": (None, rid+"_ACTIVITY.fit", None),
                        "md5": (None, hashlib.md5(data).hexdigest(), None),
                        "name": (None, 'Garmin-' + sync_item["startTimeLocal"], None),
                        "sport": (None, 3, None),  # 骑行
                        "fit_file": (rid+"_ACTIVITY.fit", data, 'application/octet-stream')
                    })
            else:
                rid     = sync_item["rideId"]
                rid     = str(rid)
                print("sync rid:" + rid)

                fit_json = "https://prod.zh.igpsport.com/service/web-gateway/web-analyze/activity/getDownloadUrl/%s" % rid
                res = session.get(fit_json)
                json_result = json.loads(res.text, strict=False)
                #判断是否存在fitUrl
                if 'data' in json_result:
                    fit_url = json_result['data']
                else:
                    print("data not found")
                    continue
                print("fit_url:" + fit_url)
                res     = session.get(fit_url)
                result = session.post(upload_url, files={
                    "file_source": (None, "undefined", None),
                    "fit_filename": (None, sync_item["startTime"]+'.fit', None),
                    "md5": (None, hashlib.md5(res.content).hexdigest(), None),
                    "name": (None, 'IGPSPORT-'+sync_item["startTime"], None),
                    "sport": (None, 3, None),  # 骑行
                    "fit_file": (sync_item["startTime"]+'.fit', res.content, 'application/octet-stream')
                })

            print("sync result:" + result.text)

activity = syncData(os.getenv("USERNAME"), os.getenv("PASSWORD"), os.getenv("GARMIN_EMAIL"), os.getenv("GARMIN_PASSWORD"))




