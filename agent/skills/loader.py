"""SkillLoader: 从 SKILL.md 文件加载 Skill 定义。

SKILL.md 格式：YAML frontmatter + markdown body。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

SKILLS_DIR = Path(__file__).parent

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class SkillDef:
    """单个 Skill 的元数据 + 内容"""
    name: str
    description: str = ""
    tools: List[str] = field(default_factory=list)
    user_invocable: bool = True
    disable_model_invocation: bool = False
    priority: int = 0
    triggers: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    content: str = ""
    file_path: str = ""


class SkillLoader:
    """扫描 agent/skills/*.md，解析 YAML frontmatter，缓存结果。"""

    def __init__(self, skills_dir: Optional[Path] = None):
        self._skills_dir = skills_dir or SKILLS_DIR
        self._skills: Dict[str, SkillDef] = {}
        self._loaded = False

    def load_all(self) -> Dict[str, SkillDef]:
        if self._loaded:
            return self._skills
        self._skills.clear()
        for path in sorted(self._skills_dir.glob("*.md")):
            skill = self._parse_file(path)
            if skill:
                self._skills[skill.name] = skill
        self._loaded = True
        return self._skills

    def _parse_file(self, path: Path) -> Optional[SkillDef]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        match = _FRONTMATTER_RE.match(text)
        if not match:
            return None

        try:
            meta = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return None

        if not isinstance(meta, dict) or not meta.get("name"):
            return None

        body = text[match.end():].strip()
        return SkillDef(
            name=meta["name"],
            description=meta.get("description", ""),
            tools=meta.get("tools", []),
            user_invocable=meta.get("user_invocable", True),
            disable_model_invocation=meta.get("disable_model_invocation", False),
            priority=meta.get("priority", 0),
            triggers=meta.get("triggers", []),
            depends_on=meta.get("depends_on", []),
            content=body,
            file_path=str(path),
        )

    def get(self, name: str) -> Optional[SkillDef]:
        self.load_all()
        return self._skills.get(name)

    def get_content(self, name: str) -> Optional[str]:
        skill = self.get(name)
        return skill.content if skill else None

    def list_skills(self) -> List[str]:
        self.load_all()
        return list(self._skills.keys())

    def get_catalog(self) -> str:
        """紧凑的 Skill 目录，注入 system prompt。"""
        self.load_all()
        skills = sorted(self._skills.values(), key=lambda s: s.priority, reverse=True)
        lines = []
        for s in skills:
            flags = []
            if s.disable_model_invocation:
                flags.append("仅手动")
            if not s.user_invocable:
                flags.append("仅LLM")
            flag_str = f" [{','.join(flags)}]" if flags else ""
            lines.append(f"  /{s.name}{flag_str} — {s.description}")
        if not lines:
            return ""
        return "可用技能（需要时调用 load_skill 加载）：\n" + "\n".join(lines)

    def get_catalog_for_tool(self) -> str:
        """用于 load_skill 工具 description 的技能列表。"""
        self.load_all()
        skills = sorted(self._skills.values(), key=lambda s: s.priority, reverse=True)
        lines = []
        for s in skills:
            lines.append(f"/{s.name}: {s.description}")
        return "\n".join(lines)

    def reload(self):
        self._loaded = False

    def __len__(self):
        self.load_all()
        return len(self._skills)
