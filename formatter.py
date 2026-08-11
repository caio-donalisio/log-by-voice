"""Schema, format functions, wiki resolver, and RESUMO — all in one file."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ===================================================================
# Schema
# ===================================================================

ItemType = Literal["task","habit_log","comment","mark_done","correction","complement","recurring_task","undo"]
HabitType = Literal["weight","piano","lifting","cardio","food","expense"]
Priority = Literal["urgente","alta","média"]
MealType = Literal["café da manhã","almoço","lanche","jantar"]
ExpenseCategory = Literal["Mercado","Restaurantes","Moradia","Saúde","Transporte","Educação","Lazer","Pets","Negócio","Outros"]

@dataclass
class TaskData:
    description: str; priority: Priority|None = None; due_date: str|None = None
    time: str|None = None; comment: str|None = None

@dataclass
class WeightData: weight_kg: float

@dataclass
class PianoData:
    piece_hint: str; minutes: int|None = None
    action: Literal["practice","study"]|None = None

@dataclass
class LiftingData:
    exercise_hint: str; weight_kg: float|None = None
    reps: int|None = None; sets: int|None = None

@dataclass
class CardioData: activity: str; minutes: int|None = None

@dataclass
class FoodData:
    description: str; calories: int|None = None
    estimated: bool = False; meal: MealType|None = None

@dataclass
class ExpenseData:
    description: str; amount: float|None = None; category: ExpenseCategory|None = None

@dataclass
class CommentData: text: str

@dataclass
class MarkDoneData:
    task_hint: str; comment: str|None = None; is_recurring: bool = False

@dataclass
class CorrectionData:
    search_hint: str; new_field: str; new_value: str
    search_scope: Literal["today","recent"] = "today"

@dataclass
class ComplementData: search_hint: str; detail: str

@dataclass
class RecurringTaskData:
    description: str; frequency: str; due_day: int|None = None
    is_payment: bool = False; priority: Priority|None = None; due_date: str|None = None

@dataclass
class Item:
    type: ItemType
    data: TaskData|WeightData|PianoData|LiftingData|CardioData|FoodData|ExpenseData|CommentData|MarkDoneData|CorrectionData|ComplementData|RecurringTaskData
    habit: HabitType|None = None
    source: str = ""
    confidence: float = 0.0

_VT = {"task","habit_log","comment","mark_done","correction","complement","recurring_task","undo"}
_VH = {"weight","piano","lifting","cardio","food","expense"}
_VC = {"Mercado","Restaurantes","Moradia","Saúde","Transporte","Educação","Lazer","Pets","Negócio","Outros"}
_DRE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TRE = re.compile(r"^\d{1,2}:\d{2}$")

def validate_item(raw: dict) -> Item:
    try:
        t, data, habit, src, conf = raw.get("type",""), raw.get("data",{}), raw.get("habit"), raw.get("_source", raw.get("source","")), float(raw.get("_confidence", raw.get("confidence",0)))
        if t not in _VT: return _fc(raw, src, f"Unknown type: {t}")
        if t == "habit_log":
            if habit not in _VH: return _fc(raw, src, f"Unknown habit: {habit}")
            d = _vh(habit, data)
        elif t == "task": d = TaskData(str(data.get("description","")), _op(data.get("priority")), _od(data.get("due_date")), _ot(data.get("time")), _os(data.get("comment")))
        elif t == "comment": d = CommentData(str(data.get("text","")))
        elif t == "mark_done": d = MarkDoneData(str(data.get("task_hint","")), _os(data.get("comment")), bool(data.get("is_recurring",False)))
        elif t == "correction": d = CorrectionData(str(data.get("search_hint","")), str(data.get("new_field","")), str(data.get("new_value","")), data.get("search_scope","today"))
        elif t == "complement": d = ComplementData(str(data.get("search_hint","")), str(data.get("detail","")))
        elif t == "recurring_task": d = RecurringTaskData(str(data.get("description","")), str(data.get("frequency","")), _oi(data.get("due_day")), bool(data.get("is_payment",False)), _op(data.get("priority")), _od(data.get("due_date")))
        elif t == "undo": d = MarkDoneData(str(data.get("task_hint","")))
        return Item(t, d, habit, src, conf)
    except Exception: return _fc(raw, raw.get("_source",""), "Validation exception")

def _vh(h, d):
    if h == "weight": return WeightData(float(d.get("weight_kg",0)))
    if h == "piano": return PianoData(str(d.get("piece_hint","")), _oi(d.get("minutes")), d.get("action"))
    if h == "lifting": return LiftingData(str(d.get("exercise_hint","")), _of(d.get("weight_kg")), _oi(d.get("reps")), _oi(d.get("sets")))
    if h == "cardio": return CardioData(str(d.get("activity","")), _oi(d.get("minutes")))
    if h == "food": return FoodData(str(d.get("description","")), _oi(d.get("calories")), bool(d.get("estimated",False)), d.get("meal"))
    if h == "expense":
        amt = _of(d.get("amount")); cat = d.get("category")
        return ExpenseData(str(d.get("description","")), amt, cat if cat in _VC else None)
    return CommentData(str(d))

def _fc(raw, src, reason):
    t = str(raw.get("data", raw))[:500]
    return Item("comment", CommentData(f"[fallback: {reason}] {t}"), source=src)

_os=lambda v: str(v).strip() if v and str(v).strip() else None
_oi=lambda v: int(v) if v is not None and str(v).lstrip("-").isdigit() else None
_of=lambda v: float(v) if v is not None else None
_op=lambda v: v if v in ("urgente","alta","média") else None
_od=lambda v: str(v).strip() if v and _DRE.match(str(v).strip()) else None
_ot=lambda v: str(v).strip() if v and _TRE.match(str(v).strip()) else None

# ===================================================================
# Format functions
# ===================================================================

_PM = {"urgente":"🔺","alta":"⏫","média":"🔼"}

def format_task(data: TaskData, time_str: str = "") -> str:
    parts = ["- [ ]", data.description]
    if data.priority and data.priority in _PM: parts.append(_PM[data.priority])
    if time_str: parts.append(f"[time:: {time_str}]")
    if data.due_date: parts.append(f"📅 {data.due_date}")
    line = " ".join(parts)
    sub = []
    if data.time: sub.append(f"    - Às {data.time}")
    if data.comment: sub.append(f"    - {data.comment}")
    return line + "\n" + "\n".join(sub) if sub else line

def format_comment(data: CommentData) -> str: return f"- {data.text}"

def _fn(n: float) -> str: return str(int(n)) if n == int(n) else f"{n:.1f}"

def format_weight(data: WeightData, time_str: str = "") -> str:
    line = f"- Me pesei [weight:: {_fn(data.weight_kg)}]"
    if time_str: line += f" [time:: {time_str}]"
    return line + " #log/fitness #fitness/weight"

def format_cardio(data: CardioData, date_str: str, time_str: str = "") -> str:
    a = (data.activity or "Cardio").capitalize()
    line = f"- [x] Fazer {a}"
    if data.minutes: line += f" [minutes:: {data.minutes}]"
    if time_str: line += f" [time:: {time_str}]"
    return line + f" #habit #fitness #fitness/cardio #log/fitness 📅 {date_str} ✅ {date_str}"

def format_food(data: FoodData, time_str: str = "") -> str:
    desc = data.description
    if data.estimated and data.calories: desc += " (estimativa)"
    line = f"- Comi {desc}"
    if data.calories: line += f" [calories:: {data.calories}]"
    if data.meal: line += f" [meal:: {data.meal}]"
    if time_str: line += f" [time:: {time_str}]"
    return line + " #log/fitness #fitness/calories"

def format_expense(data: ExpenseData, time_str: str = "") -> str:
    line = f"- Paguei {data.description}"
    if data.amount is not None: line += f" [amount:: {_fn(data.amount)}]"
    if data.category: line += f" [category:: {data.category}]"
    if time_str: line += f" [time:: {time_str}]"
    return line + " #log/finance #finance/expense"

def format_piano(data: PianoData, resolved: str|None = None, time_str: str = "") -> str:
    piece = resolved or data.piece_hint
    verb = "Estudei" if data.action == "study" else "Pratiquei"
    line = f"- {verb} [[{piece}]]"
    if data.minutes: line += f" [minutes:: {data.minutes}]"
    if time_str: line += f" [time:: {time_str}]"
    tag = "#piano/theory" if data.action == "study" else "#piano/repertoire"
    return line + f" #log/piano {tag}"

def format_lifting(data: LiftingData, resolved: str|None = None, time_str: str = "") -> str:
    ex = resolved or data.exercise_hint
    line = f"- [[{ex}]]"
    if data.weight_kg is not None: line += f" [weight:: {_fn(data.weight_kg)}]"
    if data.reps is not None: line += f" [reps:: {data.reps}]"
    if data.sets is not None: line += f" [sets:: {data.sets}]"
    if time_str: line += f" [time:: {time_str}]"
    return line + " #log/fitness #fitness/lifting"

# ===================================================================
# Wiki resolver
# ===================================================================

def _norm(s: str) -> str:
    s = s.lower(); s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", " ", s).strip()

def resolve_piece(hint: str, vault_dir: Path) -> tuple[str, float]:
    return _best_match(hint, vault_dir, ["70 Piano"])

def resolve_exercise(hint: str, vault_dir: Path) -> tuple[str, float]:
    return _best_match(hint, vault_dir, ["100 Fitness/Exercícios"])

def _best_match(hint: str, vault_dir: Path, dirs: list[str]) -> tuple[str, float]:
    nh = _norm(hint)
    if not nh: return hint, 0.0
    cand = []
    for d in dirs:
        sp = vault_dir / d
        if not sp.is_dir(): continue
        for f in sp.rglob("*.md"):
            ns = _norm(f.stem)
            if not ns: continue
            if nh == ns: cand.append((f.stem, 1.0))
            elif nh in ns: cand.append((f.stem, 0.90))
            elif ns in nh: cand.append((f.stem, 0.85))
            else:
                o = len(set(nh.split()) & set(ns.split())) / max(len(nh.split()),1)
                if o > 0.5: cand.append((f.stem, o * 0.70))
    if not cand: return hint, 0.0
    cand.sort(key=lambda x: -x[1])
    return cand[0]

# ===================================================================
# RESUMO
# ===================================================================

def generate_resumo(items: list[Item], target_files: list[str], undo_ids: list[str],
                     warnings: list[str], daily_note_created: bool = False) -> str:
    if not items and not warnings: return "RESUMO: Nenhum item processado."
    parts = []
    for i, (item, target) in enumerate(zip(items, target_files)):
        desc = _di(item, target)
        if desc:
            uid = undo_ids[i] if i < len(undo_ids) else "?"
            parts.append(f"[{uid}] {desc}")
    if daily_note_created: parts.append("nota diária criada")
    for w in warnings: parts.append(f"⚠️ {w}")
    if not parts: return "RESUMO: Nenhum item processado."
    return "RESUMO: " + "; ".join(parts) + "."

def _di(item: Item, target: str) -> str:
    d, t, h = item.data, item.type, item.habit
    w = target.replace(".md","") if target and target != "?" else "nota do dia"
    if t == "habit_log" and h == "weight": return f"Peso {d.weight_kg}kg em {w}"
    if t == "habit_log" and h == "cardio":
        m = f" ({d.minutes}min)" if getattr(d,'minutes',None) else ""
        return f"{_cap(getattr(d,'activity','Cardio'))}{m} em {w}"
    if t == "habit_log" and h == "food":
        c = f" ({d.calories} kcal)" if getattr(d,'calories',None) else ""
        return f"Comi {getattr(d,'description','refeição')}{c} em {w}"
    if t == "habit_log" and h == "expense":
        a = f" R${d.amount:.2f}" if getattr(d,'amount',None) else ""
        return f"Paguei {getattr(d,'description','gasto')}{a} em {w}"
    if t == "habit_log" and h == "piano":
        m = f" ({d.minutes}min)" if getattr(d,'minutes',None) else ""
        return f"Piano: {getattr(d,'piece_hint','peça')}{m} em {w}"
    if t == "habit_log" and h == "lifting":
        ex = getattr(d,'exercise_hint','exercício')
        s = f" {d.sets}x" if getattr(d,'sets',None) else ""
        r = str(d.reps) if getattr(d,'reps',None) else ""
        kg = f" @{d.weight_kg}kg" if getattr(d,'weight_kg',None) else ""
        return f"Musculação: {ex}{s}{r}{kg} em {w}"
    if t == "task":
        due = f" 📅 {d.due_date}" if getattr(d,'due_date',None) else ""
        return f"Tarefa \"{getattr(d,'description','tarefa')}\"{due} em {w}"
    if t == "comment":
        txt = getattr(d,'text','anotação')
        return f"Anotação \"{txt[:80]}{'...' if len(txt)>80 else ''}\" em {w}"
    if t == "mark_done": return f"Tarefa \"{getattr(d,'task_hint','tarefa')}\" concluída ✅ em {w}"
    if t == "correction": return f"Correção em \"{getattr(d,'search_hint','item')}\" em {w}"
    if t == "complement": return f"Detalhe adicionado em \"{getattr(d,'search_hint','item')}\" em {w}"
    if t == "recurring_task": return f"Tarefa recorrente \"{getattr(d,'description','tarefa')}\" em {w}"
    if t == "undo": return f"Desfeito: \"{getattr(d,'task_hint','tarefa')}\" em {w}"
    return ""

def _cap(s: str) -> str: return s[0].upper() + s[1:] if s else ""
