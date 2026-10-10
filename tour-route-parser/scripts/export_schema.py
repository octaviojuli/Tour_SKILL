"""Write schema/route-content.schema.json and schema/route-tags.schema.json from the contracts."""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from route_kit.models import SCHEMA, RouteContent  # noqa: E402
from route_kit.tags.models import SCHEMA as TAGS_SCHEMA  # noqa: E402
from route_kit.tags.models import RouteTags  # noqa: E402

schema = RouteContent.model_json_schema(by_alias=True)
schema["title"] = "RouteContent"
schema["$comment"] = f"{SCHEMA}: one itinerary attachment read into evidence-linked fields"
(root / "schema" / "route-content.schema.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=1)
)
tags = RouteTags.model_json_schema(by_alias=True)
tags["title"] = "RouteTags"
tags["$comment"] = f"{TAGS_SCHEMA}: structured labels computed from a route-kit/1 record, reviewed before use"
(root / "schema" / "route-tags.schema.json").write_text(json.dumps(tags, ensure_ascii=False, indent=1))
print("written")
