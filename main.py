import io
import os
import json
import csv
import math
from datetime import date, datetime, timedelta
import hashlib
import logging
from pathlib import Path
from threading import Timer
import time
from zoneinfo import ZoneInfo
import requests

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from starlette.responses import FileResponse, PlainTextResponse

from app.data import ReservoirCrawler, RESERVOIR_GROUPS


logger = logging.getLogger(__name__)

TPE_TIMEZONE = ZoneInfo("Asia/Taipei")

TSV_FROM_FILE = ''
TSV_SUPPLEMENTAL = ''  # 歷史檔案裡面缺少的固定資料點（每月 1, 8, 15, 22 日）
TSV_LATEST = ''  # 此刻的最新資料

TRMNL_PLUGIN_ID = ""

PREV_UPDATE_TIME = datetime.now().timestamp()
NEXT_UPDATE_TIME = datetime.now().timestamp()
UPDATE_INTERVAL = 3600
UPDATE_TIMER: Timer = None


# CURR_DATA[{水庫名稱}] = [最大蓄水量, 目前蓄水量]
CURR_DATA: dict[str, list[float]] = {}
TSV_CURR: str = ''

def load_tsv_files():
    global TSV_FROM_FILE
    this_year = datetime.now().year

    contents: list[str] = []
    for year in range(2003, this_year + 1):
        tsv_file = Path(f'public/reservoir-history/{year}.tsv')
        if tsv_file.exists():
            contents.append(tsv_file.read_text(encoding='utf8'))
        else:
            logger.warning(f"找不到 {tsv_file}")

    TSV_FROM_FILE = "".join(contents)
    tsv_to_curr_data(TSV_FROM_FILE)


def tsv_to_curr_data(tsv: str):
    global TSV_CURR

    now = datetime.now(tz=TPE_TIMEZONE)
    delta_7 = timedelta(days=7)
    for line in tsv.split('\n'):
        fields = line.split('\t')

        if len(fields) != 4:
            continue

        name, max, curr, dt_str = fields

        dt = datetime.strptime(dt_str, '%Y-%m-%d').astimezone(tz=TPE_TIMEZONE)
        too_old = now - dt > delta_7

        max_f = float(max)
        curr_f = float(curr)

        if name not in CURR_DATA:
            CURR_DATA[name] = [-1.0, -1.0]
        if max_f > 0:
            CURR_DATA[name][0] = max_f
        if curr_f > 0 and not too_old:
            CURR_DATA[name][1] = curr_f

    TSV_CURR = '\n'.join(f"{name}\t{max}\t{curr}" for name, (max, curr) in CURR_DATA.items())


def livespan(app: FastAPI):
    global UPDATE_TIMER

    logger.warning("[startup] 從檔案載入歷史資料")
    load_tsv_files()

    logger.warning("[startup] 排定撈最新資料")

    def updater():
        global NEXT_UPDATE_TIME, PREV_UPDATE_TIME, UPDATE_TIMER

        logger.warning("[updater] 啟動")
        interval = UPDATE_INTERVAL
        try:
            fetch_new_data()
            PREV_UPDATE_TIME = time.time()
        except:
            logger.exception("[updater] 更新資料時發生錯誤")
            interval = 2000

        if TRMNL_PLUGIN_ID != "":
            generate_data_for_trmnl()

        NEXT_UPDATE_TIME = time.time() + interval

        logger.warning("[updater] 結束，將於 %s 秒後再次執行", interval)
        UPDATE_TIMER = Timer(interval, updater)
        UPDATE_TIMER.start()

    UPDATE_TIMER = Timer(1, updater)
    UPDATE_TIMER.start()
    logger.warning("[startup] 排定更新資料")

    yield

    UPDATE_TIMER.cancel()
    logger.warning("[shutdown] 已關閉 updater")


app = FastAPI(lifespan=livespan)


@app.get("/")
@app.get("/favicon.png")
@app.get("/github.svg")
@app.get("/plurk.svg")
@app.get("/robots.txt")
@app.get("/tw.svg")
async def static_file(request: Request):
    path = request.url.path
    if path == '/':
        path = '/index.html'

    return FileResponse(f'public{path}')


@app.get("/api/reservoir-history.tsv")
async def reservoir_history():
    now = time.time()

    cache_time = max(int(NEXT_UPDATE_TIME - now), 0) + 30
    full_tsv = TSV_FROM_FILE + TSV_SUPPLEMENTAL + TSV_LATEST

    headers = {
        'etag': hashlib.md5(full_tsv.encode()).hexdigest(),
        'Cache-Control': f'public, max-age={cache_time}',
        'x-update-time': datetime.fromtimestamp(PREV_UPDATE_TIME, tz=TPE_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S'),
    }
    return PlainTextResponse(full_tsv, headers=headers)


@app.get("/api/curr.tsv")
async def curr():
    now = time.time()

    cache_time = max(int(NEXT_UPDATE_TIME - now), 0) + 30

    headers = {
        'etag': hashlib.md5(TSV_CURR.encode()).hexdigest(),
        'Cache-Control': f'public, max-age={cache_time}',
        'x-update-time': datetime.fromtimestamp(PREV_UPDATE_TIME, tz=TPE_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S'),
    }
    return PlainTextResponse(TSV_CURR, headers=headers)


def fetch_new_data():
    global TSV_SUPPLEMENTAL, TSV_LATEST, TSV_CURR

    logger.warning("[fetch_new_data] 開始")

    # 更新固定資料點的資料
    tsv = TSV_SUPPLEMENTAL if TSV_SUPPLEMENTAL else TSV_FROM_FILE
    last_date_str = tsv[-11:-1]

    yy, mm, dd = map(lambda val_str: int(val_str), last_date_str.split("-"))
    last_date = date(yy, mm, dd)

    logger.warning(f"最新資料時間是 {last_date}，撈取更新的資料")

    crawer = ReservoirCrawler()
    TSV_SUPPLEMENTAL += crawer.fetch_uppdated_as_tsv(begin_date=last_date)
    logger.warning("[fetch_new_data] 固定資料點已更新")

    # 拉最新的資料
    today_str = datetime.now(TPE_TIMEZONE).strftime('%Y-%m-%d')
    crawed_data = crawer.fetch()

    if len(crawed_data) <= 0:
        logger.info("crawed_data is empty")
        return

    lines = [f"{name}\t{max}\t{curr}\t{today_str}\n"
                for name, (max, curr) in crawed_data.items()]
    TSV_LATEST = "".join(lines)

    # 紀錄目前蓄水量/最大蓄水量
    logger.warning("[fetch_new_data] 更新水庫目前蓄水量/最大蓄水量")
    tsv_to_curr_data(TSV_SUPPLEMENTAL)
    tsv_to_curr_data(TSV_LATEST)

    logger.warning("[fetch_new_data] 最新資料點已更新")

def generate_data_for_trmnl():
    full_tsv = TSV_FROM_FILE + TSV_SUPPLEMENTAL + TSV_LATEST

    day_delta = 8

    ret = {}
    reservoir_arr = [
        "翡翠水庫",
        "石門水庫",
        "寶山第二水庫",
        "德基水庫",
        "日月潭水庫",
        # "鯉魚潭水庫",
        "曾文水庫",
        # "南化水庫",
    ]
    full_dict = dict()

    ret['curr'] = ""
    ret['prev'] = ""
    ret['worst'] = ""

    for reservoir in reservoir_arr:
        full_dict.setdefault(reservoir, dict())

    full_tsv = TSV_FROM_FILE + TSV_SUPPLEMENTAL + TSV_LATEST
    tsv_file = io.StringIO(full_tsv)
    csv_reader = csv.reader(tsv_file, delimiter='\t')
    for row in csv_reader:
        name, max, level, record_date = row
        if not name in full_dict:
            continue
        max = float(max)
        level = float(level)
        if max == -1 or level == -1 or max == 0:
            percent = 0
        else:
            percent = level / max
            # Somehow reservoir level can overflow !?
            if percent > 1:
                percent = 1
        full_dict[name].setdefault(record_date, percent)

    def update_data(year):
        data = ""
        start_date = datetime(year=year, month=1, day=1).date()
        end_date   = datetime(year=year+1, month=1, day=1).date()
        today = datetime.now(ZoneInfo("Asia/Taipei")).date()
        idx = 0
        current_date = start_date
        while current_date < end_date and current_date < today:
            current_date_str = current_date.strftime('%Y-%m-%d')
            level_arr = []

            for r in reservoir_arr:
                offset = 1
                while True:
                    latter_date_str = (current_date + timedelta(days=offset)).strftime('%Y-%m-%d')
                    earlier_date_str = (current_date - timedelta(days=offset)).strftime('%Y-%m-%d')
                    if current_date_str in full_dict[r]:
                        level_arr.append(int(full_dict[r][current_date_str] * 100))
                        break
                    elif latter_date_str in full_dict[r]:
                        level_arr.append(int(full_dict[r][latter_date_str] * 100))
                        break
                    elif earlier_date_str in full_dict[r]:
                        level_arr.append(int(full_dict[r][earlier_date_str] * 100))
                        break
                    else:
                        offset += 1

            # Compress a list of numbers (0-100) into a byte array. Each number is stored in 7 bits.
            # These data easily hit 2K size limit...
            compressed = bytearray()
            buffer = 0
            bits_in_buffer = 0
            for level in level_arr:
                # Ensure number is in valid range
                if level < 0 or level > 100:
                    raise ValueError("Numbers must be between 0 and 100")

                # Add the 7-bit number to the buffer
                buffer = (buffer << 7) | level
                bits_in_buffer += 7

                # While we have at least 8 bits, output bytes
                while bits_in_buffer >= 8:
                    bits_to_extract = bits_in_buffer - 8
                    byte = (buffer >> bits_to_extract) & 0xFF
                    compressed.append(byte)
                    buffer &= (1 << bits_to_extract) - 1
                    bits_in_buffer -= 8

            # Add remaining bits if any (with zero padding)
            if bits_in_buffer > 0:
                byte = (buffer << (8 - bits_in_buffer)) & 0xFF
                compressed.append(byte)

            data += compressed.hex()+','
            current_date += timedelta(days=day_delta)
            idx += 1
        return data[0:-1]

    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    ret['curr'] += update_data(today.year)
    ret['prev'] += update_data(today.year-1)
    ret['worst'] += update_data(2021)
    ret['r_len'] = len(reservoir_arr)
    ret['l_len'] = math.ceil(365/day_delta)

    payload = {}
    payload['merge_variables'] = ret

    url = "https://usetrmnl.com/api/custom_plugins/" + TRMNL_PLUGIN_ID

    # print(json.dumps(payload))
    # print("json size: %d" % len(json.dumps(payload)))

    resp = requests.post(url, json=payload)
    logger.warning(resp)
    logger.warning(resp.text)

if __name__ == '__main__':

    env_trmnl_plugin_id = os.getenv("ENV_TRMNL_PLUGIN_ID")

    if env_trmnl_plugin_id is None:
        logger.warning("[startup] TRMNL plugin UUID was not set. TRMNL routine will be skipped")
    else:
        if env_trmnl_plugin_id == "null":
            logger.warning("[startup] TRMNL plugin UUID was set to `null`. TRMNL routine will be skipped")
            TRMNL_PLUGIN_ID = ""
        else:
            TRMNL_PLUGIN_ID = env_trmnl_plugin_id

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    import uvicorn
    uvicorn.run("main:app", port=80, host='0.0.0.0', reload=True, log_level='debug')
