"""网易云音乐在线搜歌与下载（免登录）。

使用三处公开接口，无需加密、无需 Cookie：
- 搜索:  POST https://music.163.com/api/search/get
- 热歌榜: GET  https://music.163.com/api/playlist/detail?id=3778678
- 取流:  GET  https://music.163.com/song/media/outer/url?id={id}.mp3 （302 到音频 CDN）

接口限制（非代码问题）：
- VIP / 无版权歌曲外链会 302 到 404，拿不到音频；本模块按 fee 字段过滤，
  全部不可用时返回 None，由上层提示用户
- 仅供个人学习使用
"""
import os
import random

import aiohttp

SEARCH_API = "https://music.163.com/api/search/get"
PLAYLIST_API = "https://music.163.com/api/playlist/detail"
HOT_PLAYLIST_ID = 3778678  # 云音乐热歌榜
OUTER_URL = "https://music.163.com/song/media/outer/url?id={song_id}.mp3"

FREE_FEE = (0, 8)  # 0=免费, 8=非会员免费畅听；1=VIP, 4=需购买专辑
MIN_FILE_BYTES = 100_000  # 小于此值视为错误页/异常文件
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_CACHE_FILES = 50

_HEADERS = {
    "Referer": "https://music.163.com",
    "User-Agent": "Mozilla/5.0 (Xiaozhi-ESP32-Server)",
}


def _artist_names(song):
    artists = song.get("artists") or song.get("artist") or []
    if isinstance(artists, dict):
        artists = [artists]
    return ", ".join(a.get("name", "") for a in artists if a)


def pick_free_track(tracks):
    """从搜索/榜单结果中过滤出可免费播放的歌曲列表。"""
    return [t for t in (tracks or []) if t.get("fee") in FREE_FEE and t.get("id")]


def parse_search_results(data, keyword):
    """从搜索 JSON 中选最佳歌曲：歌名精确匹配 > 前缀匹配 > 其他。

    返回 {"id", "name", "artist"}，无免费结果返回 None。
    """
    songs = (data or {}).get("result", {}).get("songs") or []
    free = pick_free_track(songs)
    if not free:
        return None

    def rank(song):
        name = song.get("name", "")
        # 精确匹配排最前，其次前缀匹配；sorted 稳定，同分保持接口顺序
        return (name != keyword, not name.startswith(keyword))

    best = sorted(free, key=rank)[0]
    return {
        "id": best["id"],
        "name": best.get("name", ""),
        "artist": _artist_names(best),
    }


def parse_hot_playlist(data):
    """从热歌榜 JSON 中随机取一首免费歌曲，无可用返回 None。"""
    tracks = (data or {}).get("result", {}).get("tracks") or []
    free = pick_free_track(tracks)
    if not free:
        return None
    best = random.choice(free)
    return {
        "id": best["id"],
        "name": best.get("name", ""),
        "artist": _artist_names(best),
    }


def is_valid_download(final_url, size):
    """下载有效性判定（纯函数，便于测试）。"""
    return "/404" not in final_url and MIN_FILE_BYTES <= size <= MAX_FILE_BYTES


async def search_song(keyword, limit=20):
    """搜索歌曲并返回最佳免费结果，失败或无免费结果返回 None。"""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=timeout) as session:
            async with session.post(
                SEARCH_API, data={"s": keyword, "type": 1, "limit": limit}
            ) as resp:
                if resp.status != 200:
                    return None
                return parse_search_results(await resp.json(content_type=None), keyword)
    except (aiohttp.ClientError, TimeoutError, OSError):
        return None


async def get_hot_song():
    """从热歌榜随机取一首免费歌曲，失败返回 None。"""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=timeout) as session:
            async with session.get(
                PLAYLIST_API, params={"id": HOT_PLAYLIST_ID}
            ) as resp:
                if resp.status != 200:
                    return None
                return parse_hot_playlist(await resp.json(content_type=None))
    except (aiohttp.ClientError, TimeoutError, OSError):
        return None


async def download_song(song_id, cache_dir):
    """下载歌曲到 cache_dir/{id}.mp3（已缓存则直接复用），失败返回 None。"""
    os.makedirs(cache_dir, exist_ok=True)
    dest = os.path.join(cache_dir, f"{song_id}.mp3")
    if os.path.exists(dest) and os.path.getsize(dest) >= MIN_FILE_BYTES:
        return dest

    # ponytail: 缓存超量就整目录清空，简单够用；要保留热门再换 LRU
    try:
        cached = [f for f in os.listdir(cache_dir) if f.endswith(".mp3")]
        if len(cached) >= MAX_CACHE_FILES:
            for f in cached:
                os.remove(os.path.join(cache_dir, f))
    except OSError:
        pass

    tmp_dest = f"{dest}.part"
    try:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=timeout) as session:
            async with session.get(OUTER_URL.format(song_id=song_id)) as resp:
                if resp.status != 200:
                    return None
                size = 0
                with open(tmp_dest, "wb") as fh:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        size += len(chunk)
                        if size > MAX_FILE_BYTES:
                            raise ValueError("exceeds size limit")
                        fh.write(chunk)
                if not is_valid_download(str(resp.url), size):
                    return None
                os.replace(tmp_dest, dest)
                return dest
    except (aiohttp.ClientError, TimeoutError, OSError, ValueError):
        return None
    finally:
        if os.path.exists(tmp_dest):
            os.remove(tmp_dest)
