import time, urllib.request, json
job_id = '685bf188-4011-49c2-a605-22d67afc17b3'
url = 'http://localhost:8000/api/v1/backend-generator/jobs/' + job_id
for i in range(40):
    time.sleep(15)
    try:
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read())
        status = data['status']
        print('[' + str(i) + '] status=' + status)
        if status in ('completed', 'failed', 'completed_with_errors'):
            print(json.dumps(data, indent=2))
            break
    except Exception as e:
        print('[' + str(i) + '] error: ' + str(e))
        break
