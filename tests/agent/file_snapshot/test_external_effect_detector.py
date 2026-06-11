"""Tests for external_effect_detector module."""

import pytest

from myrm_agent_harness.agent.file_snapshot.external_effect_detector import detect_external_effects


class TestDetectExternalEffects:
    """Tests for detect_external_effects pure function."""

    def test_empty_command_returns_empty(self) -> None:
        assert detect_external_effects("") == []

    def test_none_like_empty(self) -> None:
        assert detect_external_effects("") == []

    # ---- Database commands ----

    @pytest.mark.parametrize("cmd", [
        "psql -c 'DROP TABLE users'",
        "mysql -u root -p db < dump.sql",
        "mysqldump --all-databases > backup.sql",
        "mongo --eval 'db.users.drop()'",
        "mongosh --eval 'db.collection.insertOne({})'",
        "mongodump --out /backup",
        "redis-cli FLUSHALL",
        "sqlite3 app.db 'DELETE FROM sessions'",
        "cqlsh -e 'TRUNCATE keyspace.table'",
        "influx write 'cpu,host=server01 value=0.64'",
    ])
    def test_database_commands(self, cmd: str) -> None:
        result = detect_external_effects(cmd)
        assert "database" in result

    def test_database_with_full_path(self) -> None:
        result = detect_external_effects("/usr/bin/psql -c 'SELECT 1'")
        assert "database" in result

    # ---- Container/Cloud commands ----

    @pytest.mark.parametrize("cmd", [
        "docker rm -f my_container",
        "docker run -d nginx",
        "podman build -t myimage .",
        "kubectl delete pod my-pod",
        "kubectl apply -f deployment.yaml",
        "helm install myrelease mychart",
        "terraform apply -auto-approve",
        "aws s3 cp file.txt s3://bucket/",
        "gcloud compute instances create vm-1",
        "az vm create --name myVM",
        "flyctl deploy",
        "heroku ps:scale web=2",
    ])
    def test_container_cloud_commands(self, cmd: str) -> None:
        result = detect_external_effects(cmd)
        assert "container_cloud" in result

    # ---- HTTP mutation: explicit -X ----

    @pytest.mark.parametrize("cmd", [
        "curl -X POST https://api.example.com/data",
        "curl -X PUT -d '{\"key\":\"val\"}' https://api.example.com/item/1",
        "curl -X DELETE https://api.example.com/item/1",
        "curl -X PATCH -d '{\"name\":\"new\"}' https://api.example.com/item/1",
        "curl -X post https://api.example.com/data",  # case insensitive
    ])
    def test_http_explicit_method(self, cmd: str) -> None:
        result = detect_external_effects(cmd)
        assert "network_mutation" in result

    # ---- HTTP mutation: implicit POST via -d/--data/-F ----

    @pytest.mark.parametrize("cmd", [
        "curl -d '{\"key\":\"value\"}' https://api.example.com/data",
        "curl --data '{\"key\":\"value\"}' https://api.example.com/data",
        "curl --data-raw '{\"json\":true}' https://api.example.com/endpoint",
        "curl --data-binary @file.bin https://api.example.com/upload",
        "curl --data-urlencode 'name=test' https://api.example.com/form",
        "curl -F 'file=@upload.zip' https://api.example.com/upload",
        "curl --form 'field=value' https://api.example.com/submit",
    ])
    def test_http_implicit_post(self, cmd: str) -> None:
        result = detect_external_effects(cmd)
        assert "network_mutation" in result

    # ---- wget ----

    @pytest.mark.parametrize("cmd", [
        "wget --post-data='key=val' https://api.example.com",
        "wget --post-file=data.json https://api.example.com",
    ])
    def test_wget_post(self, cmd: str) -> None:
        result = detect_external_effects(cmd)
        assert "network_mutation" in result

    # ---- httpie ----

    @pytest.mark.parametrize("cmd", [
        "http POST https://api.example.com/data name=test",
        "http PUT https://api.example.com/users/1 name=updated",
        "http DELETE https://api.example.com/users/1",
        "http PATCH https://api.example.com/users/1 name=patched",
        "https POST https://api.example.com data=test",
    ])
    def test_httpie_mutation(self, cmd: str) -> None:
        result = detect_external_effects(cmd)
        assert "network_mutation" in result

    # ---- docker-compose (legacy syntax) ----

    @pytest.mark.parametrize("cmd", [
        "docker-compose up -d",
        "docker-compose down",
        "docker-compose rm -f",
    ])
    def test_docker_compose_legacy(self, cmd: str) -> None:
        result = detect_external_effects(cmd)
        assert "container_cloud" in result

    # ---- Safe commands: should NOT trigger ----

    @pytest.mark.parametrize("cmd", [
        "curl https://api.example.com/status",
        "curl -H 'Authorization: Bearer tok' https://api.example.com/data",
        "curl -o output.json https://api.example.com/data",
        "wget https://example.com/file.tar.gz",
        "http GET https://api.example.com/data",
        "http https://api.example.com/status",
        "python -m http.server",
        "ls -la",
        "cat file.txt",
        "echo hello world",
        "python script.py",
        "npm install",
        "pip install requests",
        "git commit -m 'message'",
        "git clone https://github.com/user/repo",
    ])
    def test_safe_commands_no_effects(self, cmd: str) -> None:
        result = detect_external_effects(cmd)
        assert result == []

    # ---- Multiple effects ----

    def test_combined_database_and_network(self) -> None:
        cmd = "curl -d '{\"backup\":true}' https://api.com && psql -c 'VACUUM'"
        result = detect_external_effects(cmd)
        assert "database" in result
        assert "network_mutation" in result

    def test_combined_container_and_database(self) -> None:
        cmd = "docker exec db_container psql -c 'DROP TABLE temp'"
        result = detect_external_effects(cmd)
        assert "database" in result
        assert "container_cloud" in result

    # ---- Pipe handling ----

    def test_pipe_detects_second_command(self) -> None:
        cmd = "echo 'DROP TABLE' | psql"
        result = detect_external_effects(cmd)
        assert "database" in result

    # ---- Edge cases ----

    def test_curl_get_with_header_no_false_positive(self) -> None:
        cmd = "curl -s -H 'Content-Type: application/json' https://api.example.com/health"
        assert detect_external_effects(cmd) == []

    def test_curl_download_no_false_positive(self) -> None:
        cmd = "curl -L -O https://github.com/user/repo/releases/download/v1.0/binary"
        assert detect_external_effects(cmd) == []

    def test_httpie_get_no_false_positive(self) -> None:
        assert detect_external_effects("http GET https://api.com/data") == []

    def test_httpd_no_false_positive(self) -> None:
        assert detect_external_effects("httpd -k restart") == []

    def test_curl_many_options_before_data(self) -> None:
        cmd = "curl -s -S -L --retry 3 --max-time 30 -d '{\"json\":true}' https://api.com"
        assert "network_mutation" in detect_external_effects(cmd)

    def test_curl_data_flag_at_end(self) -> None:
        cmd = "curl https://api.com -d '{\"data\":1}'"
        assert "network_mutation" in detect_external_effects(cmd)

    def test_env_prefix_database(self) -> None:
        cmd = "PGPASSWORD=secret psql -c 'DROP TABLE users'"
        assert "database" in detect_external_effects(cmd)

    def test_sudo_container(self) -> None:
        cmd = "sudo docker rm -f container_name"
        assert "container_cloud" in detect_external_effects(cmd)
