"""
Psydox Admin Analytics Service

Pure-SQL aggregation queries for observability.  All methods return
plain dicts/lists — no Streamlit dependencies, safe to call from any context.

Queries target three data domains:
  1. Batch throughput — job_items table
  2. Quality metrics  — quality_results table
  3. AI usage         — ai_usage table

All methods tolerate missing data (new install, no activity) gracefully.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

_log = logging.getLogger("psydox.admin.analytics")


class AnalyticsService:
    """
    Aggregation queries for the observability dashboard.
    Instantiate once and call methods as needed.
    """

    # ── Batch / item throughput ────────────────────────────────────────────────

    def batch_summary(self, days: int = 7) -> dict:
        """
        Counts and throughput for job_items in the last `days` days.

        Returns:
          total_items  — all items created
          completed    — status = 'completed'
          failed       — status = 'failed'
          pass_rate    — completed / (completed + failed), 0 if no data
          items_per_hour — sustained throughput over the window
          by_status    — {status: count} breakdown
          top_errors   — list of (error_message, count) sorted desc, limit 10
        """
        since = time.time() - days * 86400
        try:
            from psydox.storage.database import get_db as get_connection
            db = get_connection()

            # Status breakdown
            rows = db.execute(
                "SELECT status, COUNT(*) FROM job_items WHERE created_at >= ? GROUP BY status",
                (since,),
            ).fetchall()
            by_status = {r[0]: r[1] for r in rows}
            total  = sum(by_status.values())
            compl  = by_status.get("completed", 0)
            failed = by_status.get("failed", 0)
            pass_rate = round(compl / max(1, compl + failed), 3)

            # Throughput
            span_seconds = days * 86400
            items_per_hour = round(total / (span_seconds / 3600), 1) if total else 0.0

            # Top errors
            err_rows = db.execute(
                """
                SELECT error, COUNT(*) as cnt
                FROM job_items
                WHERE status = 'failed'
                  AND error != ''
                  AND created_at >= ?
                GROUP BY error
                ORDER BY cnt DESC
                LIMIT 10
                """,
                (since,),
            ).fetchall()
            top_errors = [{"error": r[0], "count": r[1]} for r in err_rows]

            return {
                "total_items":    total,
                "completed":      compl,
                "failed":         failed,
                "pass_rate":      pass_rate,
                "items_per_hour": items_per_hour,
                "by_status":      by_status,
                "top_errors":     top_errors,
                "days":           days,
            }
        except Exception as exc:
            _log.warning("batch_summary query failed: %s", exc)
            return _empty_batch()

    def batch_daily_trend(self, days: int = 14) -> list[dict]:
        """
        Items processed per calendar day for the last `days` days.
        Returns list of {date: 'YYYY-MM-DD', completed: int, failed: int}.
        """
        since = time.time() - days * 86400
        try:
            from psydox.storage.database import get_db as get_connection
            db = get_connection()
            rows = db.execute(
                """
                SELECT date(created_at, 'unixepoch', 'localtime') as d,
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END)
                FROM job_items
                WHERE created_at >= ?
                GROUP BY d
                ORDER BY d
                """,
                (since,),
            ).fetchall()
            return [{"date": r[0], "completed": r[1], "failed": r[2]} for r in rows]
        except Exception as exc:
            _log.warning("batch_daily_trend query failed: %s", exc)
            return []

    # ── Quality metrics ────────────────────────────────────────────────────────

    def quality_summary(self, days: int = 7) -> dict:
        """
        Distribution of quality_results in the last `days` days.

        Returns:
          total         — number of quality checks run
          avg_score     — mean overall score (0–100)
          by_verdict    — {'APPROVED': n, 'REVIEW': n, 'NEEDS_FIX': n}
          pass_rate     — APPROVED / total
          score_buckets — [{'bucket': '80-100', 'count': n}, …]
        """
        since = time.time() - days * 86400
        try:
            from psydox.storage.database import get_db as get_connection
            db = get_connection()

            agg = db.execute(
                "SELECT COUNT(*), AVG(score) FROM quality_results WHERE created_at >= ?",
                (since,),
            ).fetchone()
            total     = agg[0] or 0
            avg_score = round(agg[1] or 0, 1)

            verd_rows = db.execute(
                "SELECT verdict, COUNT(*) FROM quality_results WHERE created_at >= ? GROUP BY verdict",
                (since,),
            ).fetchall()
            by_verdict = {r[0]: r[1] for r in verd_rows}
            pass_rate  = round(
                by_verdict.get("APPROVED", 0) / max(1, total), 3
            )

            # Score distribution in 20-point buckets
            bucket_rows = db.execute(
                """
                SELECT
                    CASE
                        WHEN score >= 80 THEN '80-100'
                        WHEN score >= 60 THEN '60-79'
                        WHEN score >= 40 THEN '40-59'
                        ELSE '0-39'
                    END AS bucket,
                    COUNT(*) as cnt
                FROM quality_results
                WHERE created_at >= ?
                GROUP BY bucket
                ORDER BY bucket DESC
                """,
                (since,),
            ).fetchall()
            score_buckets = [{"bucket": r[0], "count": r[1]} for r in bucket_rows]

            return {
                "total":         total,
                "avg_score":     avg_score,
                "by_verdict":    by_verdict,
                "pass_rate":     pass_rate,
                "score_buckets": score_buckets,
                "days":          days,
            }
        except Exception as exc:
            _log.warning("quality_summary query failed: %s", exc)
            return _empty_quality()

    # ── AI usage ───────────────────────────────────────────────────────────────

    def ai_usage_summary(self, days: int = 30) -> dict:
        """
        AI cost and usage aggregation from ai_usage table.

        Returns:
          total_cost     — total USD spent
          total_requests — number of generation calls
          by_feature     — [{feature_id, requests, cost_usd}] sorted by cost desc
          by_provider    — [{provider, requests, cost_usd}]
          by_model       — [{model, requests, cost_usd}]
          avg_latency_ms — mean latency across all requests
        """
        since = time.time() - days * 86400
        try:
            from psydox.storage.database import get_db as get_connection
            db = get_connection()

            agg = db.execute(
                "SELECT COUNT(*), SUM(cost_usd), AVG(latency_ms) FROM ai_usage WHERE created_at >= ?",
                (since,),
            ).fetchone()
            total_reqs    = agg[0] or 0
            total_cost    = round(agg[1] or 0.0, 4)
            avg_latency   = round(agg[2] or 0.0, 0)

            def _by_col(col: str) -> list[dict]:
                rows = db.execute(
                    f"""
                    SELECT {col}, COUNT(*), SUM(cost_usd)
                    FROM ai_usage
                    WHERE created_at >= ?
                    GROUP BY {col}
                    ORDER BY SUM(cost_usd) DESC
                    """,
                    (since,),
                ).fetchall()
                return [{"key": r[0] or "unknown", "requests": r[1], "cost_usd": round(r[2] or 0, 4)}
                        for r in rows]

            return {
                "total_cost":     total_cost,
                "total_requests": total_reqs,
                "avg_latency_ms": int(avg_latency),
                "by_feature":     _by_col("feature_id"),
                "by_provider":    _by_col("provider"),
                "by_model":       _by_col("model"),
                "days":           days,
            }
        except Exception as exc:
            _log.warning("ai_usage_summary query failed: %s", exc)
            return _empty_ai_usage()

    # ── Jobs overview ──────────────────────────────────────────────────────────

    def jobs_overview(self, days: int = 7, limit: int = 50) -> dict:
        """
        Recent jobs summary for the admin panel.

        Returns:
          by_status   — {status: count} from jobs table
          by_feature  — [{feature_id, count}]
          recent      — [{id, label, feature_id, status, created_at}] up to limit
        """
        since = time.time() - days * 86400
        try:
            from psydox.storage.database import get_db as get_connection
            db = get_connection()

            status_rows = db.execute(
                "SELECT status, COUNT(*) FROM jobs WHERE created_at >= ? GROUP BY status",
                (since,),
            ).fetchall()
            by_status = {r[0]: r[1] for r in status_rows}

            feat_rows = db.execute(
                """
                SELECT feature_id, COUNT(*) as cnt
                FROM jobs
                WHERE created_at >= ?
                GROUP BY feature_id
                ORDER BY cnt DESC
                """,
                (since,),
            ).fetchall()
            by_feature = [{"feature_id": r[0], "count": r[1]} for r in feat_rows]

            recent_rows = db.execute(
                """
                SELECT id, label, feature_id, status, created_at
                FROM jobs
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()
            recent = [
                {"id": r[0], "label": r[1], "feature_id": r[2],
                 "status": r[3], "created_at": r[4]}
                for r in recent_rows
            ]

            return {
                "by_status":  by_status,
                "by_feature": by_feature,
                "recent":     recent,
                "days":       days,
            }
        except Exception as exc:
            _log.warning("jobs_overview query failed: %s", exc)
            return {"by_status": {}, "by_feature": [], "recent": [], "days": days}


# ── Empty-result helpers (used when tables are empty or queries fail) ──────────

def _empty_batch() -> dict:
    return {
        "total_items": 0, "completed": 0, "failed": 0,
        "pass_rate": 0.0, "items_per_hour": 0.0,
        "by_status": {}, "top_errors": [], "days": 0,
    }

def _empty_quality() -> dict:
    return {
        "total": 0, "avg_score": 0.0, "by_verdict": {},
        "pass_rate": 0.0, "score_buckets": [], "days": 0,
    }

def _empty_ai_usage() -> dict:
    return {
        "total_cost": 0.0, "total_requests": 0, "avg_latency_ms": 0,
        "by_feature": [], "by_provider": [], "by_model": [], "days": 0,
    }
