"""Rebuildable fingerprints of the deterministic runners' actual inputs.

The task store remains the acceptance authority. These helpers neither save
state nor turn failed or legacy results into reusable successful results.
"""
from datetime import date
from hashlib import sha256
import json

from pydantic import BaseModel, ValidationError

from .claim_conflicts import conflict_refs
from .schema import CandidateResume
from .scoring import ALL_SECTIONS, _refs, load_rules


DEP_VERSION = "runner-inputs-v1"
MODULES = tuple(ALL_SECTIONS)
INPUT_FIELDS = ("resume", "target", "requirements", "enabled_sections", "as_of", "document_version_id")
FACTORS = {"skills", "function", "experience", "projects", "education", "industry", "leadership", "certificates"}


def _json_value(value):
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {key:_json_value(item) for key,item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _inputs(value):
    source=value if isinstance(value,dict) else {}
    result={key:_json_value(source.get(key)) for key in INPUT_FIELDS}
    if isinstance(result["resume"],dict):
        result["resume"]={key:item for key,item in result["resume"].items() if key not in {"source_text","source_sha256"}}
    return result


def _digest(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),default=str).encode("utf-8")).hexdigest()


def _work(resume, fields):
    return [{field:getattr(entry,field) for field in fields} for entry in resume.experience]


def _match_inputs(state, resume, refs):
    target=state["target"] or {}
    requirements=state["requirements"]
    result={"role":target.get("role",""),"requirements":requirements}
    as_of=state["as_of"] or date.today().isoformat()
    if requirements is None:
        return {**result,"job_description":target.get("job_description",""),"refs":refs,
                "work_dates":_work(resume,("start_date","end_date")),"as_of":as_of}
    if not isinstance(requirements,list) or not requirements or any(not isinstance(item,dict) or item.get("factor_id") not in FACTORS for item in requirements):
        return {"unrecognized_requirements":state}
    factors={item["factor_id"] for item in requirements}
    prefixes=[]
    if factors & {"projects","industry","leadership"}:
        prefixes.extend(("experience.","projects."))
    if "education" in factors:
        prefixes.append("education.")
    if "certificates" in factors:
        prefixes.append("certificates.")
    result["refs"]=refs if factors & {"skills","function"} else [ref for ref in refs if ref["path"].startswith(tuple(prefixes))]
    if "experience" in factors:
        result.update(work_tenure=_work(resume,("role","bullets","start_date","end_date")),as_of=as_of)
    return result


def module_fingerprints(inputs) -> dict[str,str]:
    state=_inputs(inputs)
    common={"dependency_version":DEP_VERSION,"rules_hash":_digest(load_rules()),
            "document_version_id":state["document_version_id"]}
    raw=state["resume"] or {}
    target=state["target"] or {}
    try:
        if not isinstance(raw,dict) or set(raw)-set(CandidateResume.model_fields) or not isinstance(target,dict) or set(target)-{"role","company","job_description"}:
            raise ValueError("Legacy or unknown input shape")
        resume=CandidateResume.model_validate(raw)
        refs=_refs(resume)
        as_of=state["as_of"] or date.today().isoformat()
        timeline=_work(resume,("company","role","heading","start_date","end_date"))
        projections={
            "match":_match_inputs(state,resume,refs),
            "experience":{"work":timeline,"as_of":as_of},
            "potential":{"refs":[ref for ref in refs if ref["path"].startswith(("experience.","projects.","education.","certificates."))]},
            "motivation":{"refs":refs,"target":{key:target.get(key,"") for key in ("role","company","job_description")}},
            "verification":{"work":timeline,"as_of":as_of,"conflict_refs":conflict_refs(resume),
                            "metric_refs":[ref for ref in refs if "bullets." in ref["path"] or ref["path"] in {"summary","self_evaluation"}]},
        }
    except (ValidationError,ValueError,TypeError,AttributeError):
        # History must remain readable. Unknown input contracts cannot justify
        # a narrow projection; include the whole bounded diagnostic input.
        projections={name:{"unrecognized_input":state} for name in MODULES}
    return {name:_digest({**common,"module":name,"input":projections[name]}) for name in MODULES}


def changed_fields(before, after) -> list[str]:
    """Return field paths only; source bodies and source hashes are excluded."""
    changes=[]
    missing=object()

    def compare(left,right,path):
        if isinstance(left,dict) and isinstance(right,dict):
            for key in sorted(set(left)|set(right)):
                compare(left.get(key,missing),right.get(key,missing),f"{path}.{key}" if path else key)
        elif isinstance(left,list) and isinstance(right,list):
            for index in range(max(len(left),len(right))):
                compare(left[index] if index<len(left) else missing,
                        right[index] if index<len(right) else missing,f"{path}.{index}")
        elif left!=right:
            changes.append(path)

    compare(_inputs(before),_inputs(after),"")
    return changes


def recompute_plan(snapshot, inputs, dimensions) -> dict:
    """Reuse only an accepted successful result with its original saved hash."""
    previous=snapshot if isinstance(snapshot,dict) else {}
    old=previous.get("module_fingerprints")
    old=old if isinstance(old,dict) else {}
    current=module_fingerprints(inputs)
    states=dimensions if isinstance(dimensions,dict) else {}
    enabled=(inputs.get("enabled_sections") if isinstance(inputs,dict) else None)
    enabled=set(MODULES if enabled is None else enabled)
    plan={"recomputed":[],"reused":[],"disabled":[],"changed_fields":changed_fields(previous,inputs)}
    for name in MODULES:
        result=states.get(name)
        if name not in enabled:
            plan["disabled"].append(name)
        elif isinstance(result,dict) and result.get("status")=="ok" and old.get(name)==current[name]:
            plan["reused"].append(name)
        else:
            plan["recomputed"].append(name)
    return plan
