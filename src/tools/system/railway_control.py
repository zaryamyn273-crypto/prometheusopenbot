"""
Railway Cloud Infrastructure & Deployment Control Module for Prometheus Bot.
Enables Master Admin to monitor service health, view deployments, inspect environment variables,
fetch build/deploy logs, and trigger instant redeploys directly via Railway GraphQL API.
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple

from src.core import config, database
from src.core.http import shared_client_ctx
from src.tools.registry import register_tool

logger = logging.getLogger(__name__)

RAILWAY_GRAPHQL_ENDPOINT = "https://backboard.railway.app/graphql/v2"


def _get_railway_headers() -> Dict[str, str]:
    token = config.get_railway_token() or os.getenv("RAILWAY_TOKEN", "") or os.getenv("RAILWAY_API_TOKEN", "")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "PrometheusRailwayManager/1.0"
    }
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


async def _execute_graphql(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = _get_railway_headers()
    if "Authorization" not in headers:
        raise ValueError("کلید دسترسی ریلوی (RAILWAY_TOKEN) تنظیم نشده است.")

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    async with shared_client_ctx("api") as client:
        resp = await client.post(RAILWAY_GRAPHQL_ENDPOINT, headers=headers, json=payload, timeout=12.0)
        if resp.status_code != 200:
            raise RuntimeError(f"خطای شبکه ریلوی (کد {resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        if "errors" in data and data["errors"]:
            err_msg = data["errors"][0].get("message", "Unknown GraphQL error")
            raise RuntimeError(f"خطای API ریلوی: {err_msg}")
        return data.get("data") or {}


async def _resolve_project_and_services() -> Tuple[str, str, Dict[str, str]]:
    """
    Returns (project_id, environment_id, {service_name: service_id}).
    Uses in-memory cache or queries Railway API.
    """
    cache_key = "RAILWAY_META_PROJECT_SERVICES"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        try:
            import json
            d = json.loads(cached)
            return d["project_id"], d["environment_id"], d["services"]
        except Exception:
            pass

    query = """
    query {
      projects {
        edges {
          node {
            id
            name
            environments {
              edges {
                node {
                  id
                  name
                }
              }
            }
            services {
              edges {
                node {
                  id
                  name
                }
              }
            }
          }
        }
      }
    }
    """
    data = await _execute_graphql(query)
    edges = (data.get("projects") or {}).get("edges") or []
    if not edges:
        raise RuntimeError("هیچ پروژه‌ای در این ورک‌اسپیس ریلوی یافت نشد.")

    # Select the target project (prefer current PROJECT_ID if set in env, else first project)
    proj_node = None
    env_proj_id = os.getenv("RAILWAY_PROJECT_ID", "").strip()
    for e in edges:
        n = e.get("node") or {}
        if env_proj_id and n.get("id") == env_proj_id:
            proj_node = n
            break
        if "prometheus" in (n.get("name") or "").lower() or "respect" in (n.get("name") or "").lower():
            proj_node = n
    if not proj_node:
        proj_node = edges[0].get("node") or {}

    proj_id = proj_node.get("id")
    env_edges = (proj_node.get("environments") or {}).get("edges") or []
    env_id = env_edges[0].get("node", {}).get("id") if env_edges else ""

    service_map = {}
    svc_edges = (proj_node.get("services") or {}).get("edges") or []
    for se in svc_edges:
        sn = se.get("node") or {}
        if sn.get("id") and sn.get("name"):
            service_map[sn["name"].lower()] = sn["id"]
            service_map[sn["id"]] = sn["id"]

    import json
    to_cache = json.dumps({"project_id": proj_id, "environment_id": env_id, "services": service_map})
    await database.kv_set_cache_async(cache_key, to_cache, expiration_ttl=600)
    return proj_id, env_id, service_map


@register_tool(
    name="railway_status_tool",
    description="استعلام زنده وضعیت سلامت، سرویس‌ها، دیپلوی‌های فعال و منابع کلاد ریلوی (Railway Cloud Dashboard) مختص فرمانده",
    category="admin"
)
async def railway_status_tool(caller_id: int = 0) -> str:
    """استعلام وضعیت سرورها، وضعیت دیپلوی و سرویس‌های در حال اجرای ریلوی."""
    try:
        from src.core.config import ADMIN_ID, is_admin_id
        if not caller_id or int(caller_id or 0) <= 0 or not is_admin_id(caller_id):
            return "⛔ این ابزار منحصراً در انحصار فرمانده ارشد سیستم است."
    except Exception:
        return "⛔ این ابزار منحصراً در انحصار فرمانده ارشد سیستم است."

    try:
        proj_id, env_id, svcs = await _resolve_project_and_services()
        query = """
        query ($projectId: String!) {
          project(id: $projectId) {
            name
            services {
              edges {
                node {
                  id
                  name
                  deployments(first: 1) {
                    edges {
                      node {
                        id
                        status
                        createdAt
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = await _execute_graphql(query, {"projectId": proj_id})
        p = data.get("project") or {}
        pname = p.get("name") or "پروژه ریلوی"

        lines = [
            "🚂 *داشبورد ابری ریلوی (Railway Infrastructure)*",
            f"• *پروژه*: `{pname}` (`{proj_id}`)",
            f"• *محیط عملیاتی*: `production` (`{env_id}`)\n",
            "📦 *وضعیت سرویس‌های فعال:*"
        ]

        for s_edge in (p.get("services") or {}).get("edges") or []:
            snode = s_edge.get("node") or {}
            sname = snode.get("name") or "سرویس"
            sid = snode.get("id") or ""
            dep_edges = (snode.get("deployments") or {}).get("edges") or []
            if dep_edges:
                last_dep = dep_edges[0].get("node") or {}
                status = last_dep.get("status") or "UNKNOWN"
                created = (last_dep.get("createdAt") or "")[:19].replace("T", " ")
                dep_id = (last_dep.get("id") or "")[:8]
                if status == "SUCCESS":
                    badge = "🟢 آنلاین و پایدار (SUCCESS)"
                elif status in ("BUILDING", "DEPLOYING"):
                    badge = "🟡 در حال بیلد / دیپلوی (BUILDING)"
                else:
                    badge = f"🔴 {status}"
                sid_str = f" (`{sid[:8]}`)" if sid else ""
                lines.append(f"• *{sname}*{sid_str}: {badge}\n  - دیپلوی: `{dep_id}` ({created} UTC)")
            else:
                lines.append(f"• *{sname}*: وضعیت اولیه")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ خطای استعلام وضعیت ریلوی: {str(e)}"


@register_tool(
    name="railway_redeploy_tool",
    description="اجرای ری‌دیپلوی فوری و بی‌درنگ ربات یا سرویس‌های دیگر روی ریلوی (Re-deploy service) با پاک‌سازی کش یا اعمال آخرین کامیت",
    category="admin"
)
async def railway_redeploy_tool(service_name: str = "prometheusopenbot", caller_id: int = 0) -> str:
    """
    :param service_name: نام سرویس مورد نظر ('prometheusopenbot', '9router', یا خالی برای ربات فعلی)
    """
    try:
        from src.core.config import ADMIN_ID, is_admin_id
        if not caller_id or int(caller_id or 0) <= 0 or not is_admin_id(caller_id):
            return "⛔ این ابزار منحصراً در انحصار فرمانده ارشد سیستم است."
    except Exception:
        return "⛔ این ابزار منحصراً در انحصار فرمانده ارشد سیستم است."

    try:
        proj_id, env_id, svcs = await _resolve_project_and_services()
        target_name = (service_name or "prometheusopenbot").strip().lower()
        target_sid = svcs.get(target_name)
        if not target_sid:
            for k, v in svcs.items():
                if target_name in k:
                    target_sid = v
                    break
        if not target_sid:
            target_sid = svcs.get("prometheusopenbot")

        if not target_sid:
            return f"❌ سرویس `{service_name}` در پروژه ریلوی یافت نشد."

        mutation = """
        mutation ($envId: String!, $serviceId: String!) {
          serviceInstanceRedeploy(environmentId: $envId, serviceId: $serviceId)
        }
        """
        data = await _execute_graphql(mutation, {"envId": env_id, "serviceId": target_sid})
        res = data.get("serviceInstanceRedeploy")
        if res:
            return (
                f"🚀 *دستور ری‌دیپلوی با موفقیت به ریلوی ارسال شد!*\n\n"
                f"• *سرویس هدف*: `{target_name}`\n"
                f"• *محیط*: `production`\n"
                f"• *وضعیت*: فرآیند بیلد کانتینر در بک‌گراند ریلوی آغاز گردید. ربات طی چند ثانیه با آخرین تغییرات بالا خواهد آمد."
            )
        return "⚠️ پاسخ نامشخص از سمت ریلوی هنگام ری‌دیپلوی."
    except Exception as e:
        return f"❌ خطا در ری‌دیپلوی ریلوی: {str(e)}"


@register_tool(
    name="railway_variables_tool",
    description="مشاهده لیست متغیرهای محیطی ثبت‌شده روی سرویس ریلوی (با حفظ امنیت کامل و ماسک کردن سکرت‌ها)",
    category="admin"
)
async def railway_variables_tool(service_name: str = "prometheusopenbot", caller_id: int = 0) -> str:
    try:
        from src.core.config import ADMIN_ID, is_admin_id
        if not caller_id or int(caller_id or 0) <= 0 or not is_admin_id(caller_id):
            return "⛔ این ابزار منحصراً در انحصار فرمانده ارشد سیستم است."
    except Exception:
        return "⛔ این ابزار منحصراً در انحصار فرمانده ارشد سیستم است."

    try:
        proj_id, env_id, svcs = await _resolve_project_and_services()
        target_name = (service_name or "prometheusopenbot").strip().lower()
        target_sid = svcs.get(target_name) or svcs.get("prometheusopenbot")
        if not target_sid:
            return f"❌ سرویس `{service_name}` یافت نشد."

        query = """
        query ($envId: String!, $projId: String!, $svcId: String!) {
          variables(environmentId: $envId, projectId: $projId, serviceId: $svcId)
        }
        """
        data = await _execute_graphql(query, {"envId": env_id, "projId": proj_id, "svcId": target_sid})
        vars_dict = data.get("variables") or {}

        lines = [f"⚙️ *متغیرهای محیطی سرویس `{target_name}` در ریلوی:*\n"]
        sensitive_keys = ("token", "key", "secret", "password", "auth", "credential", "d1_id", "kv_id", "jwt", "salt", "pass")
        for k, v in sorted(vars_dict.items()):
            if any(s in k.lower() for s in sensitive_keys):
                masked = v[:4] + "••••••••" + v[-3:] if len(str(v)) > 10 else "••••••••"
            else:
                masked = str(v)[:40]
            lines.append(f"• `{k}`: `{masked}`")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ خطا در خواندن متغیرهای ریلوی: {str(e)}"
