from __future__ import annotations

import json
from typing import Any


SSOT_DAG_SYSTEM_PROMPT = """\
You must produce exactly one unique and diverse answer. To do this, first generate a complex random string between <random_string> and </random_string>, and manipulate this string to guide any stochastic decisions within <thinking> and </thinking> tags.
Then, provide your final answer, enclosed within <answer> and </answer> tags.
"""


def candidate_json_example(artifact: str) -> dict[str, Any]:
    key = artifact.strip().lower().replace("-", "_").replace(" ", "_")

    if key in {"file_manifest", "files_manifest", "project_manifest"}:
        return {
            "candidate": {
                "seed": {
                    "random_string": "<random_string>A7kP2mQ9zR</random_string>",
                    "interpretation": "String manipulation shaped file order and module boundaries.",
                },
                "title": "Example file manifest",
                "summary": "Ordered implementation files and verification commands.",
                "payload_type": artifact,
                "payload": {
                    "artifact": artifact,
                    "markdown": "Short implementation order summary.",
                    "structure": {
                        "type": artifact,
                        "data": {
                            "files": [
                                {
                                    "path": "index.html",
                                    "purpose": "Browser entrypoint",
                                    "dependencies": [],
                                    "exports": [],
                                    "imports": ["src/main.js"],
                                    "checks": ["Loads in a browser over HTTP"],
                                }
                            ],
                            "commands": {
                                "run": "python3 -m http.server 4173 --directory .",
                                "verify": ["node --check src/main.js"],
                            },
                        },
                    },
                    "handoff_notes": ["UNFOLD each file into payload.files with exact path/content."],
                },
            }
        }

    if key in {"file_implementation", "file", "source_file", "code_file"}:
        return {
            "candidate": {
                "seed": {
                    "random_string": "<random_string>A7kP2mQ9zR</random_string>",
                    "interpretation": "String manipulation shaped implementation choices.",
                },
                "title": "Example source file",
                "summary": "One complete file implementation.",
                "payload_type": artifact,
                "payload": {
                    "artifact": artifact,
                    "files": [
                        {
                            "path": "src/main.js",
                            "content": "import { Game } from './core/game.js';\n\nnew Game('gameCanvas').start();\n",
                        }
                    ],
                    "markdown": "Implemented src/main.js.",
                    "handoff_notes": ["MATERIALIZE writes payload.files to disk."],
                },
            }
        }

    if artifact == "section_draft":
        return {
            "candidate": {
                "seed": {
                    "random_string": "<random_string>A7kP2mQ9zR</random_string>",
                    "interpretation": "String manipulation shaped section hook, pacing and wording.",
                },
                "title": "Example section title",
                "summary": "Short note about this section candidate.",
                "payload_type": "section_draft",
                "payload": {
                    "artifact": "section_draft",
                    "markdown": "Short finished section text in markdown. Only this one section, not the whole article.",
                    "structure": {
                        "type": "section_draft",
                        "source_order": 1,
                        "unit_id": "unit_1",
                        "title": "Source section title",
                    },
                    "handoff_notes": ["Keep this section in source_order position"],
                },
            }
        }

    return {
        "candidate": {
            "seed": {
                "random_string": "<random_string>A7kP2mQ9zR</random_string>",
                "interpretation": "String manipulation influenced the title, structure, tone and ordering choices.",
            },
            "title": f"Example {artifact} candidate",
            "summary": "One sentence explaining what makes this candidate distinct.",
            "payload_type": artifact,
            "payload": {
                "artifact": artifact,
                "markdown": "Useful human-readable content for this artifact.",
                "structure": {
                    "type": artifact,
                    "data": "Machine-readable structure for downstream steps.",
                },
                "handoff_notes": ["Specific constraint the next step must preserve"],
            },
        }
    }


def json_content_budget(artifact: str) -> str:
    key = artifact.strip().lower().replace("-", "_").replace(" ", "_")

    if key in {"section_draft", "section", "paragraph"}:
        return (
            "JSON size limits: candidate.title <= 90 chars, candidate.summary <= 140 chars, "
            "keep long prose out of title, summary and seed.interpretation. Put the section text in candidate.payload.markdown."
        )

    if key in {"draft", "article", "full_draft", "linkedin_post", "linkedin_article", "output"}:
        return (
            "JSON size limits: candidate.title <= 90 chars, candidate.summary <= 140 chars, "
            "candidate.seed.interpretation <= 18 words. Put long prose only in candidate.payload.markdown."
        )

    if key in {"file_manifest", "files_manifest", "project_manifest"}:
        return (
            "JSON size limits: candidate.title <= 90 chars, candidate.summary <= 140 chars. "
            "Put the ordered file list in candidate.payload.structure.data.files. Do not include file content yet."
        )

    if key in {"file_implementation", "file", "source_file", "code_file"}:
        return (
            "JSON size limits: candidate.title <= 90 chars, candidate.summary <= 140 chars. "
            "Put complete file content in candidate.payload.files[].content. Do not put code fences inside content."
        )

    return (
        "JSON size limits: candidate.title <= 90 chars, candidate.summary <= 140 chars, "
        "put reusable details in candidate.payload.structure. Use candidate.payload.markdown only when human-readable text is useful."
    )


def context_section(context_blocks: list[dict[str, Any]]) -> str:
    if not context_blocks:
        return "Runtime context: []"

    return "Runtime context from CONTEXT(...) steps. Use only when relevant:\n" + json.dumps(
        context_blocks,
        ensure_ascii=False,
        indent=2,
    )


def define_dod_prompt(task: str, dod_hint: str, context_blocks: list[dict[str, Any]]) -> str:
    schema = {
        "dod": {
            "audience": "Who the output is for",
            "output_language": "Language the final output must use",
            "desired_effect": "What the reader should feel/understand/do",
            "tone": "Tone constraints",
            "factual_safety_rules": ["Rule 1"],
            "banned_words_or_styles": ["Banned style"],
            "structure_preferences": ["Preference 1"],
            "quality_bar": ["Quality criterion"],
            "final_comment_goal": "What kind of discussion the final text should trigger",
        }
    }

    return "\n\n".join(
        [
            "You are a senior editor defining the hidden Definition of Done for a workflow.",
            "This DoD is not user-facing content. It is a judging rubric for later candidates.",
            "Infer the final output language from the task and user DoD hint. If the task explicitly asks for a language, preserve it exactly.",
            "Do not write the article. Do not generate content. Do not use markdown.",
            "Return JSON only.",
            f"Task:\n{task}",
            f"User DoD hint:\n{dod_hint}",
            context_section(context_blocks),
            "Output schema:\n" + json.dumps(schema, ensure_ascii=False, indent=2),
        ]
    )


def generate_candidate_prompt(
    artifact: str,
    task: str,
    dod: str,
    context_blocks: list[dict[str, Any]],
    accepted_context: list[dict[str, Any]],
    run_index: int,
    total_runs: int,
    prompt_config: dict[str, Any] | None = None,
    expansion_context: dict[str, Any] | None = None,
) -> str:
    artifact = artifact.strip()
    prompt_config = prompt_config or {}
    prompt_template = str(prompt_config.get("template", ""))
    seed_enabled = bool(prompt_config.get("seed", True))
    accepted_context_json = json.dumps(accepted_context, ensure_ascii=False, indent=2)
    runtime_context_json = json.dumps(context_blocks, ensure_ascii=False, indent=2)
    expansion_context_json = json.dumps(expansion_context or {}, ensure_ascii=False, indent=2)
    rendered_prompt = _render_prompt_alias(
        prompt_template,
        {
            "artifact": artifact,
            "task": task,
            "dod": dod,
            "accepted_context_json": accepted_context_json,
            "runtime_context_json": runtime_context_json,
            "expansion_context_json": expansion_context_json,
            "run_index": str(run_index),
            "total_runs": str(total_runs),
        },
    )
    schema = {
        "candidate": {
            "seed": {
                "random_string": "<random_string>...</random_string>",
                "interpretation": "How the full string influenced this candidate",
            },
            "title": "Candidate title",
            "summary": "Short difference from other candidates",
            "payload_type": artifact,
            "payload": {
                "artifact": artifact,
                "markdown": "Human-readable artifact content in markdown",
                "structure": {
                    "type": artifact,
                    "data": "Machine-readable structure when useful for downstream workflow steps",
                },
                "handoff_notes": ["Constraints or decisions the next workflow step must preserve"],
            },
        }
    }

    sections = [
        "SSoT seed protocol: enabled by system message." if seed_enabled else "SSoT seed protocol: disabled for this prompt alias.",
        f"Candidate run: {run_index} of {total_runs}.",
        f"Artifact to generate: {artifact}",
        f"Task:\n{task}",
        f"Definition of Done:\n{dod}",
        "Language contract: write the artifact in the language explicitly requested by the task or Definition of Done. If none is explicit, use the task's primary language.",
        context_section(context_blocks),
        "Accepted context from previous workflow stages. Treat accepted candidates as constraints, not suggestions:",
        accepted_context_json,
        _expansion_context_section(expansion_context),
        _prompt_alias_section(artifact, rendered_prompt),
        _deliverable_contract(artifact, expansion_context),
        "Generate exactly one candidate for the requested artifact.",
        json_content_budget(artifact),
        "The payload.markdown field must be useful but compact unless this artifact is explicitly a draft/output artifact.",
        "The payload.structure field should contain structured data if the next workflow step may need to reuse parts of this artifact.",
        _candidate_response_instruction(seed_enabled),
        _candidate_seed_storage_instruction(seed_enabled),
        "Valid response example. Keep this JSON shape, replace values with real content:\n"
        + json.dumps(candidate_json_example(artifact), ensure_ascii=False, indent=2),
        "Schema:\n" + json.dumps(schema, ensure_ascii=False, indent=2),
    ]

    return "\n\n".join(section for section in sections if section)


def explode_prompt(
    source_artifact: str,
    task: str,
    dod: str,
    source_candidate: dict[str, Any],
) -> str:
    schema = {
        "units": [
            {
                "unit_id": "unit_1",
                "title": "Unit title",
                "source_order": 1,
                "content": "Exact or near-exact source content for this unit",
                "constraints": ["Local constraints for generating a child artifact"],
                "must_preserve": ["Terms, order, claims or details that must not be changed"],
            }
        ],
        "fallback_used": False,
        "reason": "Where the units were extracted from",
    }

    return "\n\n".join(
        [
            "You are a deterministic artifact splitter.",
            "Do not rewrite, improve, summarize creatively, or add new ideas.",
            "Only extract ordered units from the source artifact.",
            "Preserve wording and source order where possible.",
            "If no list-like structure exists, return exactly one unit containing the whole artifact.",
            "Return JSON only. Do not use markdown fences.",
            "Valid response example. Keep this JSON shape, replace values with real extracted units:\n"
            + json.dumps(
                {
                    "units": [
                        {
                            "unit_id": "unit_1",
                            "title": "First source unit title",
                            "source_order": 1,
                            "content": "Exact source content for this unit",
                            "constraints": ["Do not change the original order"],
                            "must_preserve": ["Specific term or claim from the source"],
                        }
                    ],
                    "fallback_used": False,
                    "reason": "Units were extracted from the ordered source structure.",
                },
                ensure_ascii=False,
                indent=2,
            ),
            f"Source artifact name: {source_artifact}",
            f"Task:\n{task}",
            f"Definition of Done:\n{dod}",
            "Selected source candidate JSON:\n" + json.dumps(source_candidate, ensure_ascii=False, indent=2),
            "Output schema:\n" + json.dumps(schema, ensure_ascii=False, indent=2),
        ]
    )


def _expansion_context_section(expansion_context: dict[str, Any] | None) -> str:
    if not expansion_context:
        return ""

    sections = [
        "Expansion context for this candidate. Generate only for this one unit, not for the whole source artifact:",
        json.dumps(expansion_context, ensure_ascii=False, indent=2),
    ]

    if isinstance(expansion_context.get("current_unit"), dict):
        sections.append(
            "\n".join(
                [
                    "UNFOLD child artifact contract:",
                    "- Generate the actual finished child artifact for current_unit.",
                    "- Do not explain the plan.",
                    "- Do not summarize current_unit.",
                    "- Do not describe what should be written.",
                    "- Use previous_text_so_far only to continue naturally and avoid repetition.",
                    "- The output must be directly usable in the final assembled artifact.",
                    "- For file/code artifacts, output complete writable file content for current_unit, not explanation.",
                ]
            )
        )

    return "\n\n".join(sections)


def _deliverable_contract(artifact: str, expansion_context: dict[str, Any] | None) -> str:
    key = artifact.strip().lower().replace("-", "_").replace(" ", "_")

    if key in {"plan", "outline", "structure", "article_plan"}:
        return "Deliverable contract: this artifact is planning material. Make it structured enough for downstream generation."

    if key in {"file_manifest", "files_manifest", "project_manifest"}:
        return "\n".join(
            [
                "Deliverable contract: generate a machine-readable file manifest, not implementation prose.",
                "Do not write file contents in this artifact.",
                "Put ordered file units in candidate.payload.structure.data.files.",
                "Each file unit must include path, purpose, dependencies, expected imports/exports when relevant, and checks.",
                "Paths must be relative, portable, and safe for MATERIALIZE.",
            ]
        )

    if key in {"file_implementation", "file", "source_file", "code_file"}:
        return "\n".join(
            [
                "Deliverable contract: generate complete writable file artifact(s).",
                "Return candidate.payload.files as an array of objects with exact path and full content.",
                "If expansion_context.current_unit contains a path, implement that exact path.",
                "Content must be ready to write to disk; do not use markdown code fences in content.",
                "Avoid implicit globals, missing imports, TODO placeholders, ellipses, and references to files not present in the accepted manifest unless you also return those files.",
                "Preserve compatibility with MATERIALIZE and VERIFY steps.",
            ]
        )

    rules = [
        "Deliverable contract: generate the artifact itself, not commentary about the artifact.",
        "Do not output a plan, rubric, summary of instructions, or description of what should be written unless the requested artifact is explicitly a plan or summary.",
        "Avoid scaffold language such as 'this section will', 'the post should', 'the story aims', or 'purpose'.",
        "The payload.markdown must be directly usable by downstream glue as part of the final deliverable.",
    ]

    if expansion_context:
        rules.append("When expansion context is present, write only the requested unit/position while preserving continuity with neighboring context.")

    return "\n".join(rules)


def _candidate_response_instruction(seed_enabled: bool) -> str:
    if seed_enabled:
        return (
            "Return the required candidate JSON object inside the final <answer>...</answer> block. "
            "Do not use markdown fences or prose inside <answer>."
        )

    return "Return JSON only. Do not use markdown fences, <answer> tags, or prose outside JSON."


def _candidate_seed_storage_instruction(seed_enabled: bool) -> str:
    if not seed_enabled:
        return (
            "The candidate.seed fields are still required by the schema. Use candidate.seed.random_string and "
            "candidate.seed.interpretation as plain provenance fields, without SSoT tag requirements."
        )

    return (
        "Inside the candidate JSON, copy the generated <random_string>...</random_string> value into "
        "candidate.seed.random_string and briefly summarize how the string manipulation affected this candidate "
        "in candidate.seed.interpretation."
    )


def _prompt_alias_section(artifact: str, rendered_prompt: str) -> str:
    if rendered_prompt:
        return "\n".join(
            [
                f"Workspace prompt alias for artifact `{artifact}`. This is the primary generation instruction:",
                rendered_prompt,
                "If this conflicts with generic artifact guidance, follow the workspace prompt alias.",
            ]
        )

    return _artifact_guidance(artifact)


def _render_prompt_alias(template: str, values: dict[str, str]) -> str:
    rendered = template.strip()

    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)

    return rendered


def _artifact_guidance(artifact: str) -> str:
    key = artifact.strip().lower().replace("-", "_").replace(" ", "_")

    if key in {"angle", "angles", "positioning", "thesis"}:
        return "Artifact guidance: create a sharp angle, thesis, hook, reader promise, tone and explicit avoid-list. Do not write the full plan yet."

    if key in {"plan", "outline", "structure", "article_plan"}:
        return "Artifact guidance: create a concrete outline with ordered sections, section purpose, key points and dependencies. Make it structured enough for drafting."

    if key in {"file_manifest", "files_manifest", "project_manifest"}:
        return (
            "Artifact guidance: create an ordered project file manifest for code generation. "
            "Use candidate.payload.structure.data.files with path, purpose, dependencies, imports, exports and checks. "
            "Do not write file content yet."
        )

    if key in {"file_implementation", "file", "source_file", "code_file"}:
        return (
            "Artifact guidance: implement complete files. Use candidate.payload.files with exact path/content pairs. "
            "The content must be runnable after MATERIALIZE and should pass the requested VERIFY commands."
        )

    if key in {"draft", "article", "full_draft", "linkedin_post", "linkedin_article"}:
        return "Artifact guidance: create a complete draft in markdown. Preserve accepted upstream decisions and avoid generic filler."

    return "Artifact guidance: infer the artifact shape from its name and the Definition of Done. Be specific, structured and reusable by later workflow steps."


def direct_output_prompt(task: str, dod: str, context_blocks: list[dict[str, Any]]) -> str:
    schema = {
        "candidate": {
            "seed": {
                "random_string": "<random_string>...</random_string>",
                "interpretation": "How the full string influenced this candidate",
            },
            "title": "Output candidate",
            "summary": "Short difference",
            "payload_type": "output",
            "payload": {
                "markdown": "Final markdown output",
            },
        }
    }

    return "\n\n".join(
        [
            "SSoT seed protocol: enabled by system message.",
            f"Task:\n{task}",
            f"Definition of Done:\n{dod}",
            "Language contract: write the final output in the language explicitly requested by the task or Definition of Done. If none is explicit, use the task's primary language.",
            context_section(context_blocks),
            "Generate one complete output candidate.",
            _candidate_response_instruction(seed_enabled=True),
            _candidate_seed_storage_instruction(seed_enabled=True),
            "Valid response example. Keep this JSON shape, replace values with real content:\n"
            + json.dumps(candidate_json_example("output"), ensure_ascii=False, indent=2),
            "Schema:\n" + json.dumps(schema, ensure_ascii=False, indent=2),
        ]
    )


def judge_prompt(task: str, dod: str, stage: str, candidates: list[dict[str, Any]], context_blocks: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "task": "Choose exactly one candidate that best satisfies the Definition of Done.",
            "stage": stage,
            "source_task": task,
            "dod": dod,
            "runtime_context": context_blocks,
            "selection_rules": [
                "Do not ask for new candidates.",
                "Do not rewrite candidates.",
                "Pick the best available candidate even if all candidates are imperfect.",
                "Treat language fit as part of task fit: prefer candidates that follow the requested or implied output language.",
                "Prefer specificity, structure, and task fit over safe generic language.",
            ],
            "candidates": candidates,
            "output_schema": {
                "selected_index": 0,
                "score": 0,
                "reason": "short reason",
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def raw_glue(task: str, dod: str, selected_payload: dict[str, Any]) -> str:
    if "markdown" in selected_payload:
        return str(selected_payload["markdown"]).strip()

    if "thesis" in selected_payload:
        lines = [f"# {task}", "", f"_DoD: {dod}_", "", "## Angle", ""]
        lines.append(f"Thesis: {selected_payload.get('thesis', '')}")
        lines.append(f"Hook: {selected_payload.get('hook', '')}")
        lines.append(f"Reader promise: {selected_payload.get('reader_promise', '')}")
        lines.append(f"Tone: {selected_payload.get('tone', '')}")
        avoid = selected_payload.get("avoid", [])
        if isinstance(avoid, list) and avoid:
            lines.append("")
            lines.append("Avoid:")
            for item in avoid:
                lines.append(f"- {item}")
        return "\n".join(lines).strip()

    if "items" in selected_payload:
        lines = [f"# {task}", "", f"_DoD: {dod}_", ""]

        for index, item in enumerate(selected_payload["items"], start=1):
            lines.append(f"## {index}. {item.get('title', 'Untitled')}")
            lines.append("")
            purpose = str(item.get("purpose", "")).strip()
            if purpose:
                lines.append(purpose)
                lines.append("")

            key_points = item.get("key_points", [])
            if isinstance(key_points, list):
                for point in key_points:
                    lines.append(f"- {point}")
                lines.append("")

        return "\n".join(lines).strip()

    return json.dumps(selected_payload, ensure_ascii=False, indent=2)


def ai_glue_prompt(
    glue_mode: str,
    raw_output: str,
    context_blocks: list[dict[str, Any]],
    accepted_candidates: list[dict[str, Any]],
) -> str:
    mode_rules = _glue_mode_rules(glue_mode, raw_output)
    return "\n\n".join(
        [
            "You are the final assembly pass.",
    f"Glue mode: {glue_mode}",
    context_section(context_blocks),

    "Accepted candidates are selected source material. They are not untouchable blocks.",
    "Your job is to transform selected artifacts into one final deliverable while removing seams and semantic repetition.",

    "Rules:",
    "1. Preserve the accepted candidates' order of ideas and core meaning.",
    "2. Preserve the requested or implied output language from the task, Definition of Done, and accepted candidates.",
    "3. Preserve the intended deliverable type from the task and Definition of Done.",
    "4. Do not summarize selected candidates.",
    "5. Do not describe the workflow, plan, rubric, source material, or what the final output should do.",
    "6. Do not invent new claims, arguments, examples, facts, or conclusions.",
    "7. You may lightly edit, merge, compress, or omit parts only when they repeat the same idea semantically or expose scaffold language.",
    "8. If multiple candidates express the same point, keep the strongest, clearest, most specific version.",
    "9. When merging repeated candidates, preserve any unique useful detail from weaker versions and absorb it into the kept version.",
    "10. Add connective tissue between the remaining seams so the output feels like one continuous finished deliverable, not separate blocks.",
    "11. Do not keep two passages that make the same logical point unless the second one adds a genuinely new angle, example, consequence, or contrast.",
    "12. Remove scaffold language such as section purposes, plan labels, rubric labels, handoff notes, and meta-commentary.",
    "13. Return only the final assembled deliverable.",
    mode_rules,

    "Internal process:",
    "First, silently identify the intended final deliverable type.",
    "Then remove planning/scaffold language and semantic duplicates.",
    "Then preserve concrete non-duplicate content.",
    "Finally, assemble the remaining material into one coherent final output.",

    "Accepted candidates JSON:\n" + json.dumps(accepted_candidates, ensure_ascii=False, indent=2),
    "Raw glued output:\n" + raw_output,
        ]
    )


def _glue_mode_rules(glue_mode: str, raw_output: str) -> str:
    normalized = glue_mode.strip().lower()

    if normalized == "assemble":
        return "\n".join(
            [
                "Mode-specific rules for assemble:",
                "- Preserve nearly all non-duplicate source content.",
                "- Do not summarize.",
                "- Do not shorten for concision.",
                f"- Target length: 90-115% of raw glued output length ({len(raw_output)} characters).",
                "- You must perform final assembly edits; do not return the raw glued output unchanged.",
                "- Remove only exact or near-exact duplicate passages.",
                "- Remove scaffold labels, section headings, handoff notes and obvious seams.",
                "- Normalize transitions between adjacent fragments so the result reads as one continuous deliverable.",
                "- If the raw output already looks good, still make minimal necessary assembly edits: trim duplicate headings, smooth paragraph joins, normalize formatting and remove obvious seams.",
                "- Add short transitions only when needed.",
                "- Return the full assembled deliverable.",
            ]
        )

    if normalized == "compress":
        return "\n".join(
            [
                "Mode-specific rules for compress:",
                "- Prefer concise final output.",
                "- Merge repeated ideas aggressively.",
                "- Preserve the strongest concrete details.",
            ]
        )

    return "Mode-specific rules: apply the requested glue mode only when it does not conflict with the final assembly rules above."


def edit_prompt(
    mode: str,
    raw_output: str,
    context_blocks: list[dict[str, Any]],
    accepted_candidates: list[dict[str, Any]],
) -> str:
    return ai_glue_prompt(mode, raw_output, context_blocks, accepted_candidates)
