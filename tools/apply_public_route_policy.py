#!/usr/bin/env python3
"""Apply production public-route policy to defend_control/orchestrator.py in-place.

Commercial behavior:
- Local health timeout stays 30s
- Public route health timeout is independent (90s)
- Public probe failure keeps API/frontend up and marks stack degraded
- External cloudflared detector prefers exact config match, else unique tunnel-name match
"""
from pathlib import Path
import sys


def apply(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    old_detector_tail = (
        "            if (\n"
        '                "tunnel" not in normalized[1:run_index]\n'
        "                or run_index + 1 >= len(argv)\n"
        "                or argv[run_index + 1] != settings.cloudflared_tunnel\n"
        "                or not self._has_config(argv, settings.cloudflared_config)\n"
        "            ):\n"
        "                continue\n"
        "            matches.append(pid)\n"
        "        return matches[0] if len(matches) == 1 else None"
    )

    new_detector_tail = (
        '            if "tunnel" not in normalized[1:run_index]:\n'
        "                continue\n"
        "            tunnel_name = settings.cloudflared_tunnel\n"
        "            exact_config = self._has_config(argv, settings.cloudflared_config)\n"
        "            named = (\n"
        "                run_index + 1 < len(argv)\n"
        "                and argv[run_index + 1] == tunnel_name\n"
        "            ) or any(item == tunnel_name for item in argv)\n"
        "            if exact_config and named:\n"
        "                exact_matches.append(pid)\n"
        "            elif named:\n"
        "                name_matches.append(pid)\n"
        "        if len(exact_matches) == 1:\n"
        "            return exact_matches[0]\n"
        "        if len(name_matches) == 1:\n"
        "            return name_matches[0]\n"
        "        return None"
    )

    if "exact_matches" not in text:
        if "        matches: list[int] = []" not in text:
            raise SystemExit("unexpected detector shape")
        text = text.replace(
            "        matches: list[int] = []",
            "        exact_matches: list[int] = []\n        name_matches: list[int] = []",
            1,
        )
        if old_detector_tail not in text:
            raise SystemExit("detector tail not found")
        text = text.replace(old_detector_tail, new_detector_tail, 1)

    old_init = (
        "        health_timeout_seconds: float = 30.0,\n"
        "        poll_interval_seconds: float = 0.2,"
    )
    new_init = (
        "        health_timeout_seconds: float = 30.0,\n"
        "        public_health_timeout_seconds: float = 90.0,\n"
        "        poll_interval_seconds: float = 0.2,"
    )
    if "public_health_timeout_seconds" not in text:
        if old_init not in text:
            raise SystemExit("init signature not found")
        text = text.replace(old_init, new_init, 1)
        old_validate = (
            "        if health_timeout_seconds <= 0 or poll_interval_seconds < 0:\n"
            '            raise ValueError("health timing values are invalid")\n'
            "        self._settings = settings"
        )
        new_validate = (
            "        if health_timeout_seconds <= 0 or poll_interval_seconds < 0:\n"
            '            raise ValueError("health timing values are invalid")\n'
            "        if public_health_timeout_seconds <= 0:\n"
            '            raise ValueError("public health timing values are invalid")\n'
            "        self._settings = settings"
        )
        text = text.replace(old_validate, new_validate, 1)
        old_store = (
            "        self._health_timeout_seconds = float(health_timeout_seconds)\n"
            "        self._poll_interval_seconds = float(poll_interval_seconds)"
        )
        new_store = (
            "        self._health_timeout_seconds = float(health_timeout_seconds)\n"
            "        self._public_health_timeout_seconds = float(public_health_timeout_seconds)\n"
            "        self._poll_interval_seconds = float(poll_interval_seconds)"
        )
        text = text.replace(old_store, new_store, 1)

    old_wait = (
        "    def _wait_healthy(\n"
        "        self,\n"
        "        component: str,\n"
        "        url: str,\n"
        "        cancellation: StartCancellation,\n"
        "        *,\n"
        "        public: bool = False,\n"
        "    ) -> None:\n"
        "        deadline = time.monotonic() + self._health_timeout_seconds"
    )
    new_wait = (
        "    def _wait_healthy(\n"
        "        self,\n"
        "        component: str,\n"
        "        url: str,\n"
        "        cancellation: StartCancellation,\n"
        "        *,\n"
        "        public: bool = False,\n"
        "        timeout_seconds: float | None = None,\n"
        "    ) -> None:\n"
        "        limit = (\n"
        "            float(timeout_seconds)\n"
        "            if timeout_seconds is not None\n"
        "            else (\n"
        "                self._public_health_timeout_seconds\n"
        "                if public\n"
        "                else self._health_timeout_seconds\n"
        "            )\n"
        "        )\n"
        "        if limit <= 0:\n"
        '            raise ValueError("health timeout must be positive")\n'
        "        deadline = time.monotonic() + limit"
    )
    if "timeout_seconds: float | None = None" not in text:
        if old_wait not in text:
            raise SystemExit("wait_healthy not found")
        text = text.replace(old_wait, new_wait, 1)

    old_fail = (
        "        except StartFailed as error:\n"
        "            self._rollback(attempt)\n"
        '            self._set_state("failed", error=str(error))\n'
        "            raise"
    )
    new_fail = (
        "        except StartFailed as error:\n"
        "            # Public edge lag must not tear down a healthy local stack or an\n"
        "            # already-provisioned remote model. Degrade instead of hard-fail.\n"
        '            if error.component == "public route":\n'
        '                self._set_component("cloudflare", "degraded")\n'
        "                self._set_state(\n"
        '                    "degraded",\n'
        "                    error=(\n"
        '                        "Local API and frontend are up; public route is not healthy yet. "\n'
        '                        f"{error}"\n'
        "                    ),\n"
        "                )\n"
        "                return self.snapshot()\n"
        "            self._rollback(attempt)\n"
        '            self._set_state("failed", error=str(error))\n'
        "            raise"
    )
    if 'error.component == "public route"' not in text:
        if old_fail not in text:
            raise SystemExit("StartFailed handler not found")
        text = text.replace(old_fail, new_fail, 1)

    path.write_text(text, encoding="utf-8")
    print(f"patched {path}")


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "defend_control/orchestrator.py")
    apply(target)
