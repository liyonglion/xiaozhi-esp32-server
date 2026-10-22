"""mcp_services/netease_mcp/netease_music.py 纯逻辑测试（网络路径由端到端手动验证）。"""
from mcp_services.netease_mcp.netease_music import (
    is_valid_download,
    parse_hot_playlist,
    parse_search_results,
    pick_free_track,
)


def _song(id_, name, fee, artists=None):
    return {
        "id": id_,
        "name": name,
        "fee": fee,
        "artists": [{"name": a} for a in (artists or [])],
    }


class TestParseSearchResults:
    def test_prefers_exact_name_match_over_first_result(self):
        data = {
            "result": {
                "songs": [
                    _song(1, "晴天(深情版)", 0),
                    _song(2, "晴天", 0),
                ]
            }
        }
        assert parse_search_results(data, "晴天")["id"] == 2

    def test_prefix_match_beats_plain_order(self):
        data = {
            "result": {
                "songs": [
                    _song(1, "别的歌", 0),
                    _song(2, "晴天 Remix", 0),
                ]
            }
        }
        assert parse_search_results(data, "晴天")["id"] == 2

    def test_filters_vip_and_returns_free(self):
        data = {
            "result": {
                "songs": [
                    _song(1, "晴天", 1),  # VIP
                    _song(2, "晴天(cover)", 8),  # 非会员免费
                ]
            }
        }
        assert parse_search_results(data, "晴天")["id"] == 2

    def test_returns_none_when_all_vip(self):
        data = {"result": {"songs": [_song(1, "晴天", 1), _song(2, "晴天live", 4)]}}
        assert parse_search_results(data, "晴天") is None

    def test_returns_none_on_empty_or_malformed(self):
        assert parse_search_results(None, "x") is None
        assert parse_search_results({}, "x") is None
        assert parse_search_results({"result": {}}, "x") is None

    def test_extracts_artist_names(self):
        data = {"result": {"songs": [_song(1, "晴天", 0, ["周杰伦"])]}}
        result = parse_search_results(data, "晴天")
        assert result["artist"] == "周杰伦"


class TestPickFreeTrackAndHotPlaylist:
    def test_pick_free_track_filters_by_fee(self):
        tracks = [_song(1, "a", 0), _song(2, "b", 1), _song(3, "c", 8)]
        assert [t["id"] for t in pick_free_track(tracks)] == [1, 3]

    def test_pick_free_track_skips_missing_id(self):
        tracks = [{"name": "x", "fee": 0}]
        assert pick_free_track(tracks) == []

    def test_hot_playlist_picks_from_free_only(self):
        data = {"result": {"tracks": [_song(1, "vip歌", 1), _song(2, "free歌", 0)]}}
        assert parse_hot_playlist(data)["id"] == 2

    def test_hot_playlist_none_when_no_free(self):
        data = {"result": {"tracks": [_song(1, "vip歌", 1)]}}
        assert parse_hot_playlist(data) is None


class TestIsValidDownload:
    def test_accepts_normal_download(self):
        assert is_valid_download(
            "http://m701.music.126.net/xxx.mp3", 4 * 1024 * 1024
        )

    def test_rejects_404_redirect(self):
        assert not is_valid_download("http://music.163.com/404", 500)

    def test_rejects_tiny_file(self):
        assert not is_valid_download(
            "http://m701.music.126.net/xxx.mp3", 90_000
        )

    def test_rejects_oversized_file(self):
        assert not is_valid_download(
            "http://m701.music.126.net/xxx.mp3", 31 * 1024 * 1024
        )
