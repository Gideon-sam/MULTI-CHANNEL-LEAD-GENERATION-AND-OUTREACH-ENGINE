from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_public_overview_is_interactive_and_contains_no_creator_contacts():
    html = (ROOT / "deploy/public/index.html").read_text(encoding="utf-8")
    assert "IncuBrix Growth Engine" in html
    assert 'id="theme"' in html
    assert "4,720" in html and "5,000" in html
    assert 'href="creators/"' in html
    assert "@gmail.com" not in html
    assert "@student.tce.edu" not in html


def test_nginx_profile_has_security_headers_and_health_endpoint():
    config = (ROOT / "deploy/nginx/incubrix.conf").read_text(encoding="utf-8")
    assert "X-Content-Type-Options" in config
    assert "Content-Security-Policy" in config
    assert "frame-ancestors 'none'" in config
    assert "location = /health.json" in config


def test_deploy_script_reads_root_owned_checkout_through_sudo():
    script = (ROOT / "deploy/deploy_vm.sh").read_text(encoding="utf-8")
    assert 'sudo git -C "${checkout}" rev-parse --short HEAD' in script
