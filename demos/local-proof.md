# docs-mcp-server: Local Proof (Showboat)

*2026-02-11T00:19:24Z*

This document is generated with the Showboat CLI. It captures real command output to prove local setup and a minimal offline search smoke test.

```bash
uv --version && python --version && docker --version && showboat --version && rodney --version
```

```output
uv 0.10.2
Python 3.12.8
Docker version 29.2.1, build a5c7197
0.4.0
0.3.0
```

```bash
uv run ruff format . && uv run ruff check --fix .
```

```output
195 files left unchanged
All checks passed!
```

```bash
timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95 -q
```

```output
============================= test session starts ==============================
platform linux -- Python 3.12.8, pytest-9.0.2, pluggy-1.6.0
rootdir: /home/pankaj/Personal/Code/docs-mcp-server
configfile: pyproject.toml
testpaths: tests
plugins: timeout-2.4.0, cov-7.0.0, mock-3.15.1, anyio-4.12.1, asyncio-1.3.0
timeout: 60.0s
timeout method: thread
timeout func_only: False
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 1602 items / 40 deselected / 1562 selected

tests/test_config.py ..........                                          [  0%]
tests/test_scheduler_service.py .................                        [  1%]
tests/test_sync_scheduler.py ...                                         [  1%]
tests/unit/adapters/test_filesystem_repository_more.py .......           [  2%]
tests/unit/adapters/test_indexed_search_repository.py ...                [  2%]
tests/unit/domain/test_sync_progress_more.py ..                          [  2%]
tests/unit/runtime/test_runtime_utils.py ..                              [  2%]
tests/unit/search/test_analyzers_more.py .                               [  2%]
tests/unit/search/test_schema_more.py .....                              [  3%]
tests/unit/search/test_search_models.py ..............                   [  4%]
tests/unit/search/test_segment_search_index.py ..                        [  4%]
tests/unit/search/test_simd_bm25.py ..................                   [  5%]
tests/unit/search/test_snippet_more.py ...                               [  5%]
tests/unit/search/test_sqlite_storage.py ............................... [  7%]
..                                                                       [  7%]
tests/unit/search/test_storage_factory.py .........                      [  8%]
tests/unit/test_app_builder_endpoints.py ............................... [ 10%]
..                                                                       [ 10%]
tests/unit/test_app_builder_more.py .....                                [ 10%]
tests/unit/test_app_main.py ...                                          [ 10%]
tests/unit/test_app_unit.py .............                                [ 11%]
tests/unit/test_article_extractor/test_constants.py .................... [ 12%]
...........                                                              [ 13%]
tests/unit/test_article_extractor/test_extractor.py ..................   [ 14%]
tests/unit/test_article_extractor/test_scorer.py .....................   [ 16%]
tests/unit/test_article_extractor/test_utils.py ............             [ 16%]
tests/unit/test_bloom_filter.py .............................            [ 18%]
tests/unit/test_boot_audit_service.py ..........                         [ 19%]
tests/unit/test_boot_audit_service_unit.py ........                      [ 19%]
tests/unit/test_cache_service.py ....................................... [ 22%]
.                                                                        [ 22%]
tests/unit/test_cache_service_offline.py ......                          [ 22%]
tests/unit/test_config_helpers.py ......                                 [ 23%]
tests/unit/test_config_more.py ........                                  [ 23%]
tests/unit/test_crawl_state_store.py ..................                  [ 24%]
tests/unit/test_cron_schedule.py ................                        [ 25%]
tests/unit/test_deployment_config.py ................................... [ 28%]
.......                                                                  [ 28%]
tests/unit/test_deployment_config_more.py .....                          [ 29%]
tests/unit/test_doc_fetcher.py .............                             [ 29%]
tests/unit/test_doc_fetcher_unit.py .................................... [ 32%]
................xx.x.....                                                [ 33%]
tests/unit/test_domain_model.py .................................        [ 35%]
tests/unit/test_filesystem_repository.py ............................... [ 37%]
......                                                                   [ 38%]
tests/unit/test_filesystem_unit_of_work.py ............                  [ 38%]
tests/unit/test_filesystem_unit_of_work_more.py ......                   [ 39%]
tests/unit/test_front_matter_unit.py ......                              [ 39%]
tests/unit/test_git_sync.py ......................                       [ 41%]
tests/unit/test_git_sync_scheduler_service.py .....                      [ 41%]
tests/unit/test_git_sync_scheduler_service_more.py ..................... [ 42%]
                                                                         [ 42%]
tests/unit/test_git_sync_scheduler_service_unit.py ...............       [ 43%]
tests/unit/test_index_audit.py .............                             [ 44%]
tests/unit/test_index_audit_more.py ............                         [ 45%]
tests/unit/test_indexing_utils.py ......                                 [ 45%]
tests/unit/test_keyword_service.py ......................                [ 47%]
tests/unit/test_lockfree_concurrent.py ..............                    [ 48%]
tests/unit/test_observability.py ....................................... [ 50%]
                                                                         [ 50%]
tests/unit/test_parity_extraction.py ..........................          [ 52%]
tests/unit/test_path_builder.py .............                            [ 53%]
tests/unit/test_playwright_fetcher_unit.py ........                      [ 53%]
tests/unit/test_registry.py ...                                          [ 53%]
tests/unit/test_registry_more.py ..                                      [ 53%]
tests/unit/test_repository.py ......                                     [ 54%]
tests/unit/test_root_hub_unit.py ................                        [ 55%]
tests/unit/test_runtime_health.py .                                      [ 55%]
tests/unit/test_runtime_signals.py .                                     [ 55%]
tests/unit/test_scheduler_protocol.py ....                               [ 55%]
tests/unit/test_scheduler_service_unit.py ....................           [ 56%]
tests/unit/test_search_analyzers.py ...................                  [ 58%]
tests/unit/test_search_bm25_engine.py ..................                 [ 59%]
tests/unit/test_search_code_analyzer.py .........                        [ 59%]
tests/unit/test_search_fuzzy.py .........................                [ 61%]
tests/unit/test_search_indexer.py ...................................... [ 63%]
....                                                                     [ 64%]
tests/unit/test_search_indexer_helpers.py ..............                 [ 65%]
tests/unit/test_search_indexer_more.py ........................          [ 66%]
tests/unit/test_search_metrics.py .................                      [ 67%]
tests/unit/test_search_models.py ....                                    [ 67%]
tests/unit/test_search_phrase_proximity.py .....                         [ 68%]
tests/unit/test_search_repository.py ..                                  [ 68%]
tests/unit/test_search_repository_unit.py .                              [ 68%]
tests/unit/test_search_service.py .........                              [ 69%]
tests/unit/test_search_service_layer.py ..                               [ 69%]
tests/unit/test_search_snippet.py ....................................   [ 71%]
tests/unit/test_search_stats.py ........                                 [ 72%]
tests/unit/test_search_synonyms.py ............                          [ 72%]
tests/unit/test_segment_search_index.py ...........................      [ 74%]
tests/unit/test_semantic_cache_matcher.py ...................            [ 75%]
tests/unit/test_services.py ........................                     [ 77%]
tests/unit/test_signoz_scripts.py .....................                  [ 78%]
tests/unit/test_sqlite_storage_basic.py ...                              [ 78%]
tests/unit/test_sqlite_storage_focused.py ..................             [ 79%]
tests/unit/test_storage_factory.py .......                               [ 80%]
tests/unit/test_sync_metadata_store.py ..............                    [ 81%]
tests/unit/test_sync_metadata_store_unit.py ........                     [ 81%]
tests/unit/test_sync_progress.py .................................       [ 83%]
tests/unit/test_sync_progress_store.py ..........                        [ 84%]
tests/unit/test_sync_scheduler_extra.py ......                           [ 84%]
tests/unit/test_sync_scheduler_storage.py ...                            [ 85%]
tests/unit/test_sync_scheduler_unit.py ................................. [ 87%]
.....................................................................    [ 91%]
tests/unit/test_tenant.py ...............................                [ 93%]
tests/unit/test_tenant_more.py .................                         [ 94%]
tests/unit/test_unit_of_work.py ....                                     [ 95%]
tests/unit/test_url_translator.py ..                                     [ 95%]
tests/unit/test_url_translator_unit.py .....................             [ 96%]
tests/unit/tools/test_cleanup_segments.py .............                  [ 97%]
tests/unit/tools/test_trigger_all_indexing.py ......                     [ 97%]
tests/unit/utils/test_models_defaults.py ....                            [ 97%]
tests/unit/utils/test_path_builder_more.py .....                         [ 98%]
tests/unit/utils/test_sync_discovery_runner.py .......                   [ 98%]
tests/unit/utils/test_sync_models_more.py ..                             [ 98%]
tests/unit/utils/test_sync_progress_store_more.py .                      [ 98%]
tests/unit/utils/test_sync_scheduler_metadata_more.py ...........        [ 99%]
tests/unit/utils/test_sync_scheduler_progress_more.py ......             [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.8-final-0 ________________

Name                                                        Stmts   Miss   Cover   Missing
------------------------------------------------------------------------------------------
src/docs_mcp_server/utils/crawl_state_store.py                543    122  77.53%   83, 100-101, 103-104, 263, 265, 270-272, 391-392, 410-411, 434-441, 478-479, 501-502, 564, 593-594, 630-632, 645, 653-654, 658, 663, 699-701, 719-723, 743-754, 769-785, 800, 803, 806-807, 825-826, 846-859, 884-886, 907-910, 913-916, 949-951, 957-969, 971-973, 980-981, 986-987, 989-991, 1005, 1028, 1031-1032, 1034, 1053, 1118-1121, 1127
src/docs_mcp_server/ui/dashboard.py                            16      3  81.25%   18, 31-32
src/docs_mcp_server/tenant.py                                 455     78  82.86%   126, 135, 143, 175, 193, 211-212, 214, 229, 243, 248, 255-257, 263, 265, 275, 289-294, 307-308, 312, 320-321, 325, 328-329, 335-342, 348, 354, 366-367, 373-394, 468-469, 508, 529-530, 603-620, 642
src/docs_mcp_server/services/scheduler_service.py             144     18  87.50%   233-245, 250-257
src/docs_mcp_server/utils/sync_scheduler.py                   596     71  88.09%   349, 357, 417-431, 538, 542-543, 895-904, 1108-1166, 1188-1203
src/docs_mcp_server/utils/sync_progress_store.py               73      8  89.04%   67-75
src/docs_mcp_server/app_builder.py                            457     40  91.25%   141, 203-204, 308, 316, 324, 334, 339, 345, 350, 366-367, 382, 398, 406, 410, 415, 421, 457, 484, 487, 546, 564, 584, 655, 660-664, 681-687, 738, 754-755
src/docs_mcp_server/utils/sync_metadata_store.py              168     12  92.86%   38-39, 71, 108-109, 215, 224, 231-235
src/docs_mcp_server/search/segment_search_index.py            293     16  94.54%   165-166, 205, 215, 224, 290, 362, 369, 393, 397, 399, 420, 433, 435, 491, 494
src/docs_mcp_server/adapters/indexed_search_repository.py     114      6  94.74%   96, 141, 153, 195, 198, 214
src/docs_mcp_server/utils/sync_scheduler_progress.py           79      4  94.94%   66-71
src/docs_mcp_server/runtime/health.py                          20      1  95.00%   25
src/docs_mcp_server/search/sqlite_storage.py                  440     22  95.00%   86, 88, 103, 172, 175, 212, 215, 227-235, 649-650, 654-657
src/docs_mcp_server/search/sqlite_pragmas.py                   28      1  96.43%   33
src/docs_mcp_server/search/phrase.py                           30      1  96.67%   45
src/docs_mcp_server/root_hub.py                               125      4  96.80%   60-62, 68
src/docs_mcp_server/search/bm25_engine.py                     180      3  98.33%   140, 179, 205
src/docs_mcp_server/service_layer/boot_audit_service.py       111      1  99.10%   30
src/docs_mcp_server/utils/sync_discovery_runner.py            120      1  99.17%   145
src/docs_mcp_server/search/indexer.py                         374      2  99.47%   375-376
src/docs_mcp_server/utils/sync_scheduler_metadata.py          187      1  99.47%   59
------------------------------------------------------------------------------------------
TOTAL                                                        8719    415  95.24%

55 files skipped due to complete coverage.
Coverage HTML written to dir htmlcov
Coverage XML written to file coverage.xml
Required test coverage of 95% reached. Total coverage: 95.24%
========= 1559 passed, 40 deselected, 3 xfailed, 20 warnings in 55.65s =========
```

```bash
timeout 120 uv run python integration_tests/ci_mcp_test.py
```

```output
🏗️ Setting up CI test...
🔍 Testing MCP tools...
📚 Indexing webapi-ci...
📚 Indexing gitdocs-ci...
📚 Indexing localdocs-ci...
🧪 Testing webapi-ci...
✅ webapi-ci passed
🧪 Testing gitdocs-ci...
✅ gitdocs-ci passed
🧪 Testing localdocs-ci...
✅ localdocs-ci passed
ℹ️  Skipping SigNoz smoke test (set SIGNOZ_SMOKE=1 to enable).
✅ All tests passed!
```

```bash
uv run mkdocs build --strict
```

```output
INFO    -  Cleaning site directory
INFO    -  Building documentation to directory: /home/pankaj/Personal/Code/docs-mcp-server/site
INFO    -  Documentation built in 1.79 seconds
```

```bash
set -euo pipefail; timeout 120 uv run python debug_multi_tenant.py --config deployment.example.json --tenant drf --test search --query serializers | sed -n '1,80p'
```

```output
🔒 Safety check passed: No dangerous deletion operations found
Current working directory: /home/pankaj/Personal/Code/docs-mcp-server
🔒 Running in OFFLINE mode
🎯 Filtered to 1 tenant(s) from 10 total
📝 Created debug config: /tmp/docs-mcp-server-multi-debug/deployment.debug.json
🚀 Starting multi-tenant server...
🧹 Cleaning up __pycache__ in /home/pankaj/Personal/Code/docs-mcp-server/src...
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/__pycache__
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/utils/__pycache__
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/services/__pycache__
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/observability/__pycache__
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/search/__pycache__
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/service_layer/__pycache__
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/adapters/__pycache__
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/runtime/__pycache__
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/ui/__pycache__
   -> Removing stale cache: /home/pankaj/Personal/Code/docs-mcp-server/src/docs_mcp_server/domain/__pycache__
   Config: /tmp/docs-mcp-server-multi-debug/deployment.debug.json
   Log file: /tmp/docs-mcp-server-multi-debug/server.log
   PID file: /tmp/docs-mcp-server-multi-debug/server.pid
   Waiting for server to be ready...
✅ Server ready at http://127.0.0.1:33495

--- Testing tenant: drf ---

[drf] Filesystem Tenant Test
   MCP URL: http://127.0.0.1:33495/mcp/
   Test Queries: 10 queries across 3 types
   ✅ Root hub tools available: {'root_fetch', 'root_search'}

   📝 Testing natural queries (3 queries)
   -> Testing root_search('drf', 'How to create a serializer') (word_match: False)
   ✅ Search successful, returned 5 results

📊 Search Results:
   1 {                                                                          
   2   "results": [                                                             
   3     {                                                                      
   4       "url": "https://www.django-rest-framework.org/api-guide/serializers/"
   5       "title": "Serializers",                                              
   6       "snippet": "- [Serializers](https://www.django-rest-framework.org/api
   7     },                                                                     
   8     {                                                                      
   9       "url": "https://www.django-rest-framework.org/tutorial/1-serializatio
  10       "title": "Tutorial 1: Serialization",                                
  11       "snippet": "- [Tutorial 1: Serialization](https://www.django-rest-fra
  12     },                                                                     
  13     {                                                                      
  14       "url": "https://www.django-rest-framework.org/topics/writable-nested-
  15       "title": "Writable nested serializers",                              
  16       "snippet": "- [Writable nested serializers](https://www.django-rest-f
  17     },                                                                     
  18     {                                                                      
  19       "url": "https://www.django-rest-framework.org/api-guide/relations/", 
  20       "title": "Serializer relations",                                     
  21       "snippet": "- [Serializer relations](https://www.django-rest-framewor
  22     },                                                                     
  23     {                                                                      
  24       "url": "https://www.django-rest-framework.org/tutorial/quickstart/", 
  25       "title": "Quickstart",                                               
  26       "snippet": "- [Project setup](https://www.django-rest-framework.org/t
  27     }                                                                      
  28   ],                                                                       
  29   "stats": null,                                                           
  30   "error": null,                                                           
  31   "query": null                                                            
  32 }                                                                          

   -> Testing root_search('drf', 'DRF viewset permissions') (word_match: False)
   ✅ Search successful, returned 5 results

📊 Search Results:
   1 {                                                                          
   2   "results": [                                                             
   3     {                                                                      
   4       "url": "https://www.django-rest-framework.org/api-guide/permissions/"
   5       "title": "Permissions",                                              
   6       "snippet": "- [Permissions](https://www.django-rest-framework.org/api
   7     },                                                                     
   8     {                                                                      
```
