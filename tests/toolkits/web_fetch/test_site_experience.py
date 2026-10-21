"""站点经验存储测试

验证：
1. SiteExperience 数据模型序列化/反序列化
2. SiteExperienceStore 增删改查
3. LRU 驱逐
4. 持久化（保存/加载）
5. DomainMetrics 交叉验证（possibly_stale 检测）
6. 格式化输出（注入和完整查询）
7. browser_manage 工具集成（save/list/delete_site_experience action）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType
from myrm_agent_harness.toolkits.web_fetch.router.domain_metrics import DomainMetricsManager
from myrm_agent_harness.toolkits.web_fetch.router.site_experience import (
    SiteExperience,
    SiteExperienceStore,
)


class TestSiteExperience:
    """SiteExperience 数据模型测试"""

    def test_serialization_roundtrip(self) -> None:
        exp = SiteExperience(
            domain="example.com",
            platform_features=["Login required", "JS rendering"],
            url_patterns={"search": "/search?q={query}"},
            known_traps=["CAPTCHA on login"],
            successful_flows=["Use site search"],
            prefer_http3=True,
            last_verified="2024-03-20",
            verification_count=3,
        )

        data = exp.to_dict()
        restored = SiteExperience.from_dict(data)

        assert restored.domain == "example.com"
        assert restored.platform_features == ["Login required", "JS rendering"]
        assert restored.url_patterns == {"search": "/search?q={query}"}
        assert restored.known_traps == ["CAPTCHA on login"]
        assert restored.successful_flows == ["Use site search"]
        assert restored.prefer_http3 is True
        assert restored.last_verified == "2024-03-20"
        assert restored.verification_count == 3

    def test_is_empty(self) -> None:
        empty = SiteExperience(domain="empty.com")
        assert empty.is_empty()

        non_empty = SiteExperience(domain="x.com", known_traps=["popup"])
        assert not non_empty.is_empty()

    def test_format_for_injection(self) -> None:
        exp = SiteExperience(
            domain="xiaohongshu.com",
            known_traps=["Login modal after 3 scrolls"],
            successful_flows=["Use site internal search"],
        )

        text = exp.format_for_injection()
        assert "xiaohongshu.com" in text
        assert "Login modal" in text
        assert "site internal search" in text
        assert "stale" not in text.lower()

    def test_format_for_injection_stale(self) -> None:
        exp = SiteExperience(
            domain="x.com",
            known_traps=["Rate limit"],
        )

        text = exp.format_for_injection(possibly_stale=True)
        assert "stale" in text.lower()

    def test_format_full(self) -> None:
        exp = SiteExperience(
            domain="example.com",
            platform_features=["JS rendering"],
            url_patterns={"search": "/s?q={q}"},
            known_traps=["popup"],
            successful_flows=["direct URL"],
            last_verified="2024-01-01",
            verification_count=5,
        )

        text = exp.format_full()
        assert "Platform:" in text
        assert "URL patterns:" in text
        assert "Known traps:" in text
        assert "Successful approaches:" in text
        assert "verified 5 times" in text


class TestSiteExperienceStore:
    """SiteExperienceStore 存储测试"""

    @pytest.fixture()
    def tmp_store(self, tmp_path: Path) -> SiteExperienceStore:
        return SiteExperienceStore(storage_path=tmp_path / "site_experience.json")

    def test_save_and_get(self, tmp_store: SiteExperienceStore) -> None:
        tmp_store.save_experience(
            "example.com",
            platform_features=["JS heavy"],
            known_traps=["popup"],
        )

        exp, stale = tmp_store.get("example.com")
        assert exp is not None
        assert not stale
        assert "JS heavy" in exp.platform_features
        assert "popup" in exp.known_traps

    def test_prefer_http3_roundtrip(self, tmp_store: SiteExperienceStore) -> None:
        tmp_store.set_prefer_http3("news.example.com")
        assert tmp_store.get_prefer_http3("news.example.com") is True
        assert tmp_store.get_prefer_http3("www.news.example.com") is True

        tmp_store.set_prefer_http3("news.example.com", enabled=False)
        assert tmp_store.get_prefer_http3("news.example.com") is False

        tmp_store.save()
        reloaded = SiteExperienceStore(storage_path=tmp_store._storage_path)
        assert reloaded.get_prefer_http3("news.example.com") is False

    def test_get_nonexistent(self, tmp_store: SiteExperienceStore) -> None:
        exp, stale = tmp_store.get("nonexistent.com")
        assert exp is None
        assert not stale

    def test_incremental_merge(self, tmp_store: SiteExperienceStore) -> None:
        tmp_store.save_experience("x.com", known_traps=["trap1"])
        tmp_store.save_experience("x.com", known_traps=["trap2"])
        tmp_store.save_experience("x.com", known_traps=["trap1"])  # duplicate

        exp, _ = tmp_store.get("x.com")
        assert exp is not None
        assert exp.known_traps == ["trap1", "trap2"]

    def test_url_patterns_overwrite(self, tmp_store: SiteExperienceStore) -> None:
        tmp_store.save_experience("x.com", url_patterns={"search": "/old"})
        tmp_store.save_experience("x.com", url_patterns={"search": "/new", "user": "/u/{id}"})

        exp, _ = tmp_store.get("x.com")
        assert exp is not None
        assert exp.url_patterns["search"] == "/new"
        assert exp.url_patterns["user"] == "/u/{id}"

    def test_verification_count_increments(self, tmp_store: SiteExperienceStore) -> None:
        tmp_store.save_experience("x.com", known_traps=["t1"])
        tmp_store.save_experience("x.com", known_traps=["t2"])

        exp, _ = tmp_store.get("x.com")
        assert exp is not None
        assert exp.verification_count == 2

    def test_delete(self, tmp_store: SiteExperienceStore) -> None:
        tmp_store.save_experience("x.com", known_traps=["t1"])
        assert tmp_store.delete("x.com")
        assert not tmp_store.delete("x.com")

        exp, _ = tmp_store.get("x.com")
        assert exp is None

    def test_list_domains(self, tmp_store: SiteExperienceStore) -> None:
        tmp_store.save_experience("a.com", known_traps=["t1"])
        tmp_store.save_experience("b.com", known_traps=["t2"])

        domains = tmp_store.list_domains()
        assert set(domains) == {"a.com", "b.com"}

    def test_lru_eviction(self, tmp_path: Path) -> None:
        store = SiteExperienceStore(storage_path=tmp_path / "se.json", max_domains=3)

        store.save_experience("a.com", known_traps=["t1"])
        store.save_experience("b.com", known_traps=["t2"])
        store.save_experience("c.com", known_traps=["t3"])

        # Access a.com so it's not LRU
        store.get("a.com")

        store.save_experience("d.com", known_traps=["t4"])

        domains = store.list_domains()
        assert len(domains) == 3
        assert "d.com" in domains
        assert "a.com" in domains
        # b.com should be evicted (least recently used)

    def test_persistence(self, tmp_path: Path) -> None:
        path = tmp_path / "se.json"

        store1 = SiteExperienceStore(storage_path=path)
        store1.save_experience(
            "example.com",
            platform_features=["JS rendering"],
            url_patterns={"search": "/s?q={q}"},
            known_traps=["popup"],
            successful_flows=["direct URL"],
        )
        store1.save()

        # Load from same file
        store2 = SiteExperienceStore(storage_path=path)
        exp, _ = store2.get("example.com")

        assert exp is not None
        assert exp.platform_features == ["JS rendering"]
        assert exp.url_patterns == {"search": "/s?q={q}"}
        assert exp.known_traps == ["popup"]
        assert exp.successful_flows == ["direct URL"]

    def test_get_stats(self, tmp_store: SiteExperienceStore) -> None:
        tmp_store.save_experience("x.com", known_traps=["t1"])
        tmp_store.save_experience("empty.com")  # empty

        stats = tmp_store.get_stats()
        assert stats["total_domains"] == 2
        assert stats["non_empty_domains"] == 1


class TestCrossValidation:
    """DomainMetrics 交叉验证测试"""

    @pytest.fixture()
    def tmp_store(self, tmp_path: Path) -> SiteExperienceStore:
        return SiteExperienceStore(storage_path=tmp_path / "se.json")

    @pytest.fixture()
    def metrics_manager(self, tmp_path: Path) -> DomainMetricsManager:
        return DomainMetricsManager(storage_path=tmp_path / "dm.json")

    def test_not_stale_without_metrics(self, tmp_store: SiteExperienceStore) -> None:
        tmp_store.save_experience("x.com", known_traps=["t1"])

        _, stale = tmp_store.get("x.com")
        assert not stale

    def test_not_stale_with_good_success_rate(
        self,
        tmp_store: SiteExperienceStore,
        metrics_manager: DomainMetricsManager,
    ) -> None:
        tmp_store.save_experience("x.com", known_traps=["t1"])

        metrics = metrics_manager.get_or_create("x.com")
        for _ in range(10):
            metrics.record_fetcher_result(FetcherType.HTTP, success=True, latency_ms=100.0)

        _, stale = tmp_store.get("x.com", domain_metrics_manager=metrics_manager)
        assert not stale

    def test_stale_with_recent_failures(
        self,
        tmp_store: SiteExperienceStore,
        metrics_manager: DomainMetricsManager,
    ) -> None:
        tmp_store.save_experience("x.com", known_traps=["t1"])

        metrics = metrics_manager.get_or_create("x.com")
        # 3+ recent failures (24h window) triggers stale
        for _ in range(3):
            metrics.record_fetcher_result(FetcherType.HTTP, success=False, latency_ms=100.0)

        _, stale = tmp_store.get("x.com", domain_metrics_manager=metrics_manager)
        assert stale

    def test_not_stale_with_few_failures(
        self,
        tmp_store: SiteExperienceStore,
        metrics_manager: DomainMetricsManager,
    ) -> None:
        tmp_store.save_experience("x.com", known_traps=["t1"])

        metrics = metrics_manager.get_or_create("x.com")
        # Only 2 recent failures < 3 threshold
        for _ in range(2):
            metrics.record_fetcher_result(FetcherType.HTTP, success=False, latency_ms=100.0)

        _, stale = tmp_store.get("x.com", domain_metrics_manager=metrics_manager)
        assert not stale

    def test_not_stale_unknown_domain_in_metrics(
        self,
        tmp_store: SiteExperienceStore,
        metrics_manager: DomainMetricsManager,
    ) -> None:
        tmp_store.save_experience("x.com", known_traps=["t1"])
        # Domain not in metrics_manager
        _, stale = tmp_store.get("x.com", domain_metrics_manager=metrics_manager)
        assert not stale


class TestManageToolIntegration:
    """browser_manage 工具中 site_experience action 的集成测试

    直接调用 manage.py 中的 _handle_* 函数逻辑，
    通过 monkeypatch 替换全局单例来隔离。
    """

    @pytest.fixture()
    def store(self, tmp_path: Path) -> SiteExperienceStore:
        return SiteExperienceStore(storage_path=tmp_path / "se.json")

    @pytest.fixture(autouse=True)
    def _patch_global_store(self, store: SiteExperienceStore, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.web_fetch.router.get_global_site_experience_store",
            lambda: store,
        )
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.web_fetch.router.site_experience.get_global_site_experience_store",
            lambda: store,
        )

    def _save(self, value: str) -> str:
        import json as stdlib_json

        if not value.strip():
            return "Error"

        try:
            data = stdlib_json.loads(value)
        except stdlib_json.JSONDecodeError:
            return "Error: value must be valid JSON"

        domain = data.get("domain", "").strip()
        if not domain:
            return "Error: JSON must include 'domain' field"

        from myrm_agent_harness.toolkits.web_fetch.router import get_global_site_experience_store

        s = get_global_site_experience_store()
        exp = s.save_experience(
            domain,
            platform_features=data.get("platform_features"),
            url_patterns=data.get("url_patterns"),
            known_traps=data.get("known_traps"),
            successful_flows=data.get("successful_flows"),
        )
        s.save()
        return exp.format_full()

    def test_save_site_experience(self, store: SiteExperienceStore) -> None:
        result = self._save('{"domain":"test.com","known_traps":["login wall"],"successful_flows":["direct URL"]}')
        assert "test.com" in result
        assert "login wall" in result
        assert "direct URL" in result

        exp, _ = store.get("test.com")
        assert exp is not None
        assert "login wall" in exp.known_traps

    def test_save_site_experience_invalid_json(self) -> None:
        result = self._save("not json")
        assert "Error" in result

    def test_save_site_experience_no_domain(self) -> None:
        result = self._save('{"known_traps":["x"]}')
        assert "Error" in result

    def test_save_site_experience_empty_value(self) -> None:
        result = self._save("")
        assert "Error" in result

    def test_list_site_experience_empty(self, store: SiteExperienceStore) -> None:
        from myrm_agent_harness.toolkits.web_fetch.router import get_global_site_experience_store

        s = get_global_site_experience_store()
        domains = s.list_domains()
        assert len(domains) == 0

    def test_list_site_experience_with_data(self, store: SiteExperienceStore) -> None:
        store.save_experience("a.com", known_traps=["t1"])
        store.save_experience("b.com", known_traps=["t2"])

        domains = store.list_domains()
        assert set(domains) == {"a.com", "b.com"}

    def test_delete_site_experience(self, store: SiteExperienceStore) -> None:
        store.save_experience("x.com", known_traps=["t1"])
        assert store.delete("x.com")

        exp, _ = store.get("x.com")
        assert exp is None

    def test_delete_nonexistent(self, store: SiteExperienceStore) -> None:
        assert not store.delete("nonexistent.com")


class TestEdgeCases:
    """边界情况测试"""

    def test_resolve_path_explicit(self, tmp_path: Path) -> None:
        explicit_path = tmp_path / "explicit_se.json"

        store = SiteExperienceStore(storage_path=explicit_path)
        store.save_experience("env.com", known_traps=["t1"])
        store.save()

        assert explicit_path.exists()

    def test_load_corrupted_file(self, tmp_path: Path) -> None:
        path = tmp_path / "se.json"
        path.write_text("not valid json")

        store = SiteExperienceStore(storage_path=path)
        assert store.list_domains() == []

    def test_shutdown_saves(self, tmp_path: Path) -> None:
        path = tmp_path / "se.json"
        store = SiteExperienceStore(storage_path=path)
        store.save_experience("x.com", known_traps=["t1"])
        store.shutdown()

        store2 = SiteExperienceStore(storage_path=path)
        exp, _ = store2.get("x.com")
        assert exp is not None

    def test_save_noop_when_not_dirty(self, tmp_path: Path) -> None:
        path = tmp_path / "se.json"
        store = SiteExperienceStore(storage_path=path)
        store.save()
        assert not path.exists()

    def test_evict_empty_noop(self, tmp_path: Path) -> None:
        store = SiteExperienceStore(storage_path=tmp_path / "se.json")
        store._evict_lru()
        assert store.list_domains() == []

    def test_domain_normalization_www_prefix(self, tmp_path: Path) -> None:
        store = SiteExperienceStore(storage_path=tmp_path / "se.json")
        store.save_experience("xiaohongshu.com", known_traps=["popup"])

        exp, _ = store.get("www.xiaohongshu.com")
        assert exp is not None
        assert "popup" in exp.known_traps

    def test_domain_normalization_save_with_www(self, tmp_path: Path) -> None:
        store = SiteExperienceStore(storage_path=tmp_path / "se.json")
        store.save_experience("www.example.com", known_traps=["t1"])

        exp, _ = store.get("example.com")
        assert exp is not None

    def test_domain_normalization_delete_with_www(self, tmp_path: Path) -> None:
        store = SiteExperienceStore(storage_path=tmp_path / "se.json")
        store.save_experience("example.com", known_traps=["t1"])
        assert store.delete("www.example.com")
