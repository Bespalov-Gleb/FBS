"""Подготовка КИЗ для WB meta/sgtin: полный код + GS."""

from app.services.order_complete_service import _ensure_gs_in_kiz, _prepare_kiz_for_wb

GS = "\x1d"


def test_prepare_keeps_existing_gs() -> None:
    raw = f"0104655078776010215Te+DapWt=dUa{GS}91EE11{GS}92UTVfQG10hFH8xylDZxpd7nTwdkeBfTJP6KGyfRz1FM="
    out = _prepare_kiz_for_wb(raw)
    assert out == raw
    assert out.count(GS) == 2
    assert len(out) > 31


def test_prepare_inserts_gs_into_compact_full_kiz() -> None:
    # Слитно (как после потери GS в input): head31 + 91key + 92crypto
    compact = (
        "0104655078776010215Te+DapWt=dUa"
        "91EE11"
        "92UTVfQG10hFH8xylDZxpd7nTwdkeBfTJP6KGyfRz1FM="
    )
    out = _prepare_kiz_for_wb(compact)
    assert GS in out
    assert out == (
        f"0104655078776010215Te+DapWt=dUa{GS}91EE11{GS}"
        "92UTVfQG10hFH8xylDZxpd7nTwdkeBfTJP6KGyfRz1FM="
    )


def test_prepare_does_not_truncate_to_31() -> None:
    compact = (
        "0104655078776010215Te+DapWt=dUa"
        "91EE11"
        "92UTVfQG10hFH8xylDZxpd7nTwdkeBfTJP6KGyfRz1FM="
    )
    out = _prepare_kiz_for_wb(compact)
    assert len(out) > 31
    assert out.startswith("0104655078776010215")


def test_ensure_gs_short_with_91_only() -> None:
    # Короткий формат WB: с GS, без криптохвоста 92
    s = "0104655078776010215Te+DapWt=dUa91EE11"
    out = _ensure_gs_in_kiz(s)
    assert out == f"0104655078776010215Te+DapWt=dUa{GS}91EE11"


def test_prepare_plain_31_unchanged() -> None:
    short = "0104655078776010215.uD_c>Xmi)PE"
    assert len(short) == 31
    out = _prepare_kiz_for_wb(short)
    assert out == short
    assert GS not in out
