import httpx
import asyncio
import logging
import sqlite3
from time import perf_counter
from tqdm import tqdm
from src._logger import Logger
from src.db.schema import insert_data
from src._locations import Directories
from asyncio import create_task
from bs4 import BeautifulSoup

MAIN_DIR = Directories.MAIN_DIR
DB = Directories.DB_DIR.joinpath(Directories.ENV_VALUES["DB_NAME"])
Logger().basic_logger

codes = {1: 54256, 2: 1}


async def get_response(m_code: int):
    BASE_URL: str = Directories.ENV_VALUES["BASE_URL"] + str(m_code)
    while True:
        try:
            async with httpx.AsyncClient() as aioclient:
                r = await aioclient.get(BASE_URL)
            return r, BASE_URL
        except httpx.HTTPError:
            logging.warning("Encountered httpx.HTTPERROR")
            for _ in range(0, 60):
                # print(f"will retry in {60-i}s", end=" \r")
                await asyncio.sleep(1)
            continue


async def parse_html(m_code: int):
    response, url = await get_response(m_code)
    soup = BeautifulSoup(response, "lxml")
    main_tree = soup.find("main")
    h3 = main_tree.find("h3", {"class": "text-2xl font-bold"})
    if h3 is None:
        return None, None
    manga_title = h3.find("a", {"href": True, "class": "link link-hover"})
    return manga_title.text, url


async def get_current_urlint() -> list[int]:
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("SELECT url_int FROM main")
    url_int: list[int] = [idx[0] for idx in cursor]
    return url_int


async def start_scraping(idx_lower: int, idx_upper: int, current_url_int: list[int]):
    data = []
    for idx in tqdm(range(idx_lower, idx_upper)):
        if idx not in current_url_int:
            title, url = await parse_html(idx)
            data.append({"url_int": idx, "title": title, "link": url})
            insert_data(data)  # inserts to a sqlite3 database
            data.clear()


async def lower_bound():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(url_int) FROM main")
    for max_url_int in cursor:
        if max_url_int[0] is None:
            start_from = 1
        else:
            start_from = max_url_int[0]
    return start_from


async def get_ranges(start_from: int, upper: int, workers: int):
    scrape_range = upper - start_from
    distribution = scrape_range // workers
    dist_list = []
    for idx in range(workers):
        dist_list.append(start_from + (distribution * (idx + 1)))
    dist_list[-1] = upper
    return dist_list


async def create_workers(dist_list: list[int], current_url_int: list[int]):
    queue_workers = []
    for idx, _ in enumerate(dist_list):
        if idx + 1 == len(dist_list):
            break
        queue_workers.append(
            create_task(
                start_scraping(dist_list[idx], dist_list[idx + 1], current_url_int)
            )
        )
    await asyncio.gather(*queue_workers)


async def main():
    current_url_int = await get_current_urlint()
    try:
        lower = int(input("lower limit (leave blank to set automatically): "))
    except ValueError:
        lower = await lower_bound()
        print(f"lower bound is set automaticallly: {lower}")

    upper = int(input("upper limit: "))
    workers = int(input("No. of workers: "))
    rg = await get_ranges(lower, upper, workers)
    await create_workers(rg, current_url_int)


if __name__ == "__main__":
    start = perf_counter()
    with asyncio.Runner() as runner:
        runner.run(main())
    end = perf_counter()
    print(f"Elapsed time: {end - start:.2f} seconds")
