"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { CharacterSprite, avatarLabel } from "@/components/character/CharacterSprite";
import { api } from "@/lib/api";
import type {
  CharacterAccessory,
  CharacterArchetype,
  CharacterAvatar,
  CharacterHairColor,
  CharacterHairStyle,
  CharacterOutfitColor,
  CharacterSheet,
  CharacterSkinTone,
} from "@/lib/types";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, CARD, FOCUS_RING, INPUT } from "@/lib/ui";

const ARCHETYPES: { id: CharacterArchetype; title: string; description: string; icon: string; color: string }[] = [
  { id: "scholar", title: "Scholar", description: "Turn careful understanding into steady growth.", icon: "✦", color: "sky" },
  { id: "builder", title: "Builder", description: "Stack small skills into useful systems.", icon: "◈", color: "amber" },
  { id: "explorer", title: "Explorer", description: "Follow curiosity across new branches.", icon: "◎", color: "emerald" },
  { id: "mentor", title: "Mentor", description: "Learn deeply enough to explain it clearly.", icon: "✧", color: "violet" },
];

const AVATARS: { id: CharacterAvatar; title: string; eyebrow: string }[] = [
  { id: "owl", title: "Owl", eyebrow: "Night scholar" },
  { id: "fox", title: "Fox", eyebrow: "Quick thinker" },
  { id: "robot", title: "Robot", eyebrow: "Systems mind" },
  { id: "wizard", title: "Wizard", eyebrow: "Deep diver" },
  { id: "cat", title: "Cat", eyebrow: "Curious soul" },
  { id: "dragon", title: "Dragon", eyebrow: "Bold learner" },
];

const SKIN_OPTIONS: { id: CharacterSkinTone; label: string; color: string }[] = [
  { id: "moon", label: "Moon", color: "#f3d0b5" },
  { id: "sand", label: "Sand", color: "#d8b08c" },
  { id: "honey", label: "Honey", color: "#b9784d" },
  { id: "copper", label: "Copper", color: "#8f4e38" },
  { id: "ebony", label: "Ebony", color: "#59352d" },
];
const HAIR_OPTIONS: { id: CharacterHairColor; label: string; color: string }[] = [
  { id: "ink", label: "Ink", color: "#172033" },
  { id: "chestnut", label: "Chestnut", color: "#7c2d12" },
  { id: "silver", label: "Silver", color: "#cbd5e1" },
  { id: "violet", label: "Violet", color: "#5b21b6" },
  { id: "rose", label: "Rose", color: "#be185d" },
];
const HAIR_STYLE_OPTIONS: { id: CharacterHairStyle; label: string; icon: string }[] = [
  { id: "sweep", label: "Sweep", icon: "⌁" },
  { id: "curls", label: "Curls", icon: "◌" },
  { id: "bob", label: "Bob", icon: "◒" },
  { id: "mohawk", label: "Mohawk", icon: "♠" },
  { id: "crown", label: "Crown", icon: "♛" },
];
const OUTFIT_OPTIONS: { id: CharacterOutfitColor; label: string; color: string }[] = [
  { id: "azure", label: "Azure", color: "#38bdf8" },
  { id: "violet", label: "Violet", color: "#a78bfa" },
  { id: "coral", label: "Coral", color: "#fb7185" },
  { id: "mint", label: "Mint", color: "#34d399" },
  { id: "gold", label: "Gold", color: "#fbbf24" },
];
const ACCESSORY_OPTIONS: { id: CharacterAccessory; label: string; icon: string }[] = [
  { id: "none", label: "None", icon: "—" },
  { id: "glasses", label: "Glasses", icon: "◉" },
  { id: "headband", label: "Headband", icon: "⌒" },
  { id: "crown", label: "Crown", icon: "♛" },
  { id: "earring", label: "Earring", icon: "○" },
];

const STAT_META: { key: "focus" | "memory" | "resilience" | "curiosity"; label: string; description: string; icon: string; color: string }[] = [
  { key: "focus", label: "Focus", description: "Staying with the hard part", icon: "◉", color: "sky" },
  { key: "memory", label: "Memory", description: "Keeping skills battle-ready", icon: "▣", color: "violet" },
  { key: "resilience", label: "Resilience", description: "Recovering from wrong answers", icon: "◆", color: "amber" },
  { key: "curiosity", label: "Curiosity", description: "Opening new branches", icon: "✦", color: "emerald" },
];

function ChoiceGroup<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { id: T; label: string; color?: string; icon?: string }[]; onChange: (value: T) => void }) {
  return (
    <fieldset>
      <legend className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</legend>
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map((option) => (
          <button key={option.id} type="button" onClick={() => onChange(option.id)} aria-pressed={value === option.id} className={`character-custom-choice ${value === option.id ? "character-custom-choice-selected" : ""} ${FOCUS_RING}`}>
            {option.color ? <span className="character-color-swatch" style={{ backgroundColor: option.color }} aria-hidden /> : <span className="character-choice-glyph" aria-hidden>{option.icon}</span>}
            <span>{option.label}</span>
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function CustomizationPanel({
  skinTone,
  hairStyle,
  hairColor,
  outfitColor,
  accessory,
  setSkinTone,
  setHairStyle,
  setHairColor,
  setOutfitColor,
  setAccessory,
}: {
  skinTone: CharacterSkinTone;
  hairStyle: CharacterHairStyle;
  hairColor: CharacterHairColor;
  outfitColor: CharacterOutfitColor;
  accessory: CharacterAccessory;
  setSkinTone: (value: CharacterSkinTone) => void;
  setHairStyle: (value: CharacterHairStyle) => void;
  setHairColor: (value: CharacterHairColor) => void;
  setOutfitColor: (value: CharacterOutfitColor) => void;
  setAccessory: (value: CharacterAccessory) => void;
}) {
  return (
    <div className="character-customization-panel mt-6 space-y-5">
      <div><p className="character-kicker">APPEARANCE LOADOUT</p><p className="mt-1 text-xs text-slate-500">Make this hero unmistakably yours.</p></div>
      <ChoiceGroup label="Skin tone" value={skinTone} options={SKIN_OPTIONS} onChange={setSkinTone} />
      <div className="grid gap-5 sm:grid-cols-2"><ChoiceGroup label="Hair style" value={hairStyle} options={HAIR_STYLE_OPTIONS} onChange={setHairStyle} /><ChoiceGroup label="Hair color" value={hairColor} options={HAIR_OPTIONS} onChange={setHairColor} /></div>
      <div className="grid gap-5 sm:grid-cols-2"><ChoiceGroup label="Outfit color" value={outfitColor} options={OUTFIT_OPTIONS} onChange={setOutfitColor} /><ChoiceGroup label="Accessory" value={accessory} options={ACCESSORY_OPTIONS} onChange={setAccessory} /></div>
    </div>
  );
}

function StatCard({ label, description, value, icon, color }: { label: string; description: string; value: number; icon: string; color: string }) {
  return (
    <article className="character-stat-card group">
      <div className="flex items-start justify-between gap-2">
        <span className={`character-stat-icon character-stat-icon-${color}`} aria-hidden>{icon}</span>
        <span className="font-display text-lg font-bold text-slate-100">{value}</span>
      </div>
      <h3 className="mt-4 text-sm font-semibold text-slate-100">{label}</h3>
      <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{description}</p>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div className={`character-stat-fill character-stat-fill-${color}`} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
    </article>
  );
}

function LevelProgress({ sheet }: { sheet: CharacterSheet }) {
  const percent = sheet.exp_for_next_level > 0
    ? Math.min(100, Math.round((sheet.exp_into_level / sheet.exp_for_next_level) * 100))
    : 0;

  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-sky-300">Current level</p>
          <p className="mt-1 font-display text-5xl font-extrabold tracking-[-0.06em] text-white">{sheet.level}</p>
        </div>
        <div className="text-right">
          <p className="font-display text-sm font-bold text-slate-100">{sheet.total_exp.toLocaleString()} <span className="font-body text-xs font-medium text-slate-400">EXP</span></p>
          <p className="mt-1 text-[11px] text-slate-400">{sheet.exp_into_level} / {sheet.exp_for_next_level} to level {sheet.level + 1}</p>
        </div>
      </div>
      <div className="mt-5 h-3 overflow-hidden rounded-full border border-sky-400/20 bg-slate-950/80 p-0.5" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Level progress">
        <div className="character-exp-fill h-full rounded-full" style={{ width: `${percent}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between text-[10px] font-medium uppercase tracking-wider text-slate-500">
        <span>Next milestone</span>
        <span>{percent}% charged</span>
      </div>
    </div>
  );
}

export default function CharacterPage() {
  const [sheet, setSheet] = useState<CharacterSheet | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [avatar, setAvatar] = useState<CharacterAvatar>("owl");
  const [archetype, setArchetype] = useState<CharacterArchetype>("scholar");
  const [skinTone, setSkinTone] = useState<CharacterSkinTone>("sand");
  const [hairStyle, setHairStyle] = useState<CharacterHairStyle>("sweep");
  const [hairColor, setHairColor] = useState<CharacterHairColor>("chestnut");
  const [outfitColor, setOutfitColor] = useState<CharacterOutfitColor>("azure");
  const [accessory, setAccessory] = useState<CharacterAccessory>("none");

  const refresh = useCallback(async () => {
    try {
      const next = await api.getCharacter();
      setSheet(next);
      if (next.profile) {
        setName(next.profile.character_name);
        setAvatar(AVATARS.find((item) => item.id === next.profile?.avatar_key)?.id ?? "owl");
        setArchetype(ARCHETYPES.find((item) => item.id === next.profile?.archetype)?.id ?? "scholar");
        setSkinTone(SKIN_OPTIONS.find((item) => item.id === next.profile?.skin_tone)?.id ?? "sand");
        setHairStyle(HAIR_STYLE_OPTIONS.find((item) => item.id === next.profile?.hair_style)?.id ?? "sweep");
        setHairColor(HAIR_OPTIONS.find((item) => item.id === next.profile?.hair_color)?.id ?? "chestnut");
        setOutfitColor(OUTFIT_OPTIONS.find((item) => item.id === next.profile?.outfit_color)?.id ?? "azure");
        setAccessory(ACCESSORY_OPTIONS.find((item) => item.id === next.profile?.accessory)?.id ?? "none");
      }
      setError(null);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      setSheet(await api.createCharacter(name.trim(), avatar, archetype, {
        skin_tone: skinTone,
        hair_style: hairStyle,
        hair_color: hairColor,
        outfit_color: outfitColor,
        accessory,
      }));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      setSheet(await api.updateCharacter({
        character_name: name.trim(),
        avatar_key: avatar,
        archetype,
        skin_tone: skinTone,
        hair_style: hairStyle,
        hair_color: hairColor,
        outfit_color: outfitColor,
        accessory,
      }));
      setEditing(false);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function unlock(perkId: string) {
    if (!sheet || sheet.available_perk_points < 1 || busy) return;
    setBusy(true);
    setError(null);
    try {
      setSheet(await api.unlockCharacterPerk(perkId));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <main id="main-content" className="character-shell mx-auto max-w-6xl px-4 py-10">
        <div className="character-loading-panel">
          <div className="character-loading-orb" />
          <p className="mt-4 text-sm text-slate-400">Summoning your character sheet…</p>
        </div>
      </main>
    );
  }

  if (!sheet?.profile) {
    return (
      <main id="main-content" className="character-shell mx-auto max-w-6xl px-4 py-8 sm:py-12">
        <div className="mb-8 flex items-center justify-between">
          <Link href="/courses" className="character-wordmark">LEARN<span>ANYTHING</span></Link>
          <span className="character-step-label"><span>01</span> / 01 · Create your hero</span>
        </div>
        <div className="character-create-grid overflow-hidden rounded-[2rem] border border-slate-800/80 bg-slate-900/70 shadow-2xl shadow-sky-950/20">
          <div className="character-create-stage relative flex min-h-[520px] flex-col items-center justify-center overflow-hidden p-8 text-center sm:p-12">
            <div className="character-stage-grid absolute inset-0" />
            <div className="character-orbit character-orbit-one" />
            <div className="character-orbit character-orbit-two" />
            <div className="relative z-10">
              <span className="character-floating-label">THE JOURNEY AWAITS</span>
              <CharacterSprite avatar={avatar} archetype={archetype} skinTone={skinTone} hairStyle={hairStyle} hairColor={hairColor} outfitColor={outfitColor} accessory={accessory} size="lg" animated className="mx-auto mt-5" />
              <p className="mt-3 font-display text-xs font-semibold uppercase tracking-[0.24em] text-sky-300">{avatarLabel(avatar)} · {ARCHETYPES.find((item) => item.id === archetype)?.title}</p>
              <h1 className="mt-3 font-display text-3xl font-extrabold tracking-tight text-white sm:text-4xl">Build your learning hero.</h1>
              <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-slate-400">Every answer is experience. Every skill is a new ability. Your character grows wherever your curiosity takes you.</p>
            </div>
          </div>
          <form onSubmit={create} className="p-6 sm:p-10">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-sky-300"><span className="h-1.5 w-1.5 rounded-full bg-sky-400" /> Identity setup</div>
            <h2 className="mt-3 font-display text-2xl font-bold text-white">Who will you become?</h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">Pick a look and a vibe. Your archetype shapes your style, never your ability to learn.</p>
            <label htmlFor="character-name" className="mt-7 block text-xs font-semibold text-slate-300">Character name</label>
            <input id="character-name" className={`${INPUT} mt-2 bg-slate-950/70`} value={name} onChange={(event) => setName(event.target.value)} placeholder="What should the guild call you?" maxLength={80} autoFocus />
            <fieldset className="mt-6">
              <legend className="text-xs font-semibold text-slate-300">Choose your companion</legend>
              <div className="mt-3 grid grid-cols-3 gap-2">
                {AVATARS.map((item) => (
                  <button key={item.id} type="button" onClick={() => setAvatar(item.id)} aria-pressed={avatar === item.id} className={`character-avatar-choice ${avatar === item.id ? "character-avatar-choice-selected" : ""} ${FOCUS_RING}`}>
                    <CharacterSprite avatar={item.id} archetype={archetype} skinTone={skinTone} hairStyle={hairStyle} hairColor={hairColor} outfitColor={outfitColor} accessory={accessory} size="sm" />
                    <span className="mt-1 block text-xs font-semibold text-slate-200">{item.title}</span>
                    <span className="mt-0.5 block text-[9px] text-slate-500">{item.eyebrow}</span>
                  </button>
                ))}
              </div>
            </fieldset>
            <fieldset className="mt-6">
              <legend className="text-xs font-semibold text-slate-300">Choose your archetype</legend>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {ARCHETYPES.map((item) => (
                  <button key={item.id} type="button" onClick={() => setArchetype(item.id)} aria-pressed={archetype === item.id} className={`character-archetype-choice ${archetype === item.id ? "character-archetype-choice-selected" : ""} ${FOCUS_RING}`}>
                    <span className="character-archetype-icon">{item.icon}</span>
                    <span className="min-w-0"><span className="block text-left text-xs font-semibold text-slate-100">{item.title}</span><span className="mt-0.5 block text-left text-[10px] leading-relaxed text-slate-500">{item.description}</span></span>
                  </button>
                ))}
              </div>
            </fieldset>
            <CustomizationPanel skinTone={skinTone} hairStyle={hairStyle} hairColor={hairColor} outfitColor={outfitColor} accessory={accessory} setSkinTone={setSkinTone} setHairStyle={setHairStyle} setHairColor={setHairColor} setOutfitColor={setOutfitColor} setAccessory={setAccessory} />
            {error && <p role="alert" className="mt-5 text-sm text-rose-400">{error}</p>}
            <button type="submit" disabled={busy || !name.trim()} className={`mt-7 w-full ${BUTTON_PRIMARY} character-cta-button`}>{busy ? "Joining the guild…" : "Enter the world →"}</button>
            <p className="mt-3 text-center text-[10px] text-slate-500">You can customize your character later.</p>
          </form>
        </div>
      </main>
    );
  }

  const profile = sheet.profile;
  const currentAvatar = avatar;
  const currentArchetype = ARCHETYPES.find((item) => item.id === archetype) ?? ARCHETYPES[0];
  const unlockedPerks = new Set(sheet.perks.filter((perk) => perk.unlocked).map((perk) => perk.id));
  const achievementCount = sheet.achievements.filter((achievement) => achievement.unlocked).length;
  const totalAchievementCount = sheet.achievements.length;
  const streakLabel = sheet.streak_days > 0 ? `${sheet.streak_days} day${sheet.streak_days === 1 ? "" : "s"}` : "Ready to start";
  const statCards = STAT_META.map((meta) => ({ ...meta, value: sheet.stats[meta.key] }));

  return (
    <main id="main-content" tabIndex={-1} className="character-shell mx-auto max-w-6xl px-4 py-6 outline-none sm:py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3"><Link href="/courses" className="character-wordmark">LEARN<span>ANYTHING</span></Link><span className="hidden text-slate-700 sm:inline">/</span><span className="hidden text-xs font-medium text-slate-500 sm:inline">Character hall</span></div>
        <div className="flex items-center gap-2"><Link href="/quests" className={`character-top-link ${FOCUS_RING}`}>Quest board</Link><button type="button" onClick={() => setEditing((current) => !current)} className={`character-top-link ${FOCUS_RING}`}>{editing ? "Close editor" : "Customize"}</button></div>
      </div>

      {error && <p role="alert" className="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{error}</p>}

      {editing && (
        <form onSubmit={saveProfile} className="character-editor mt-5 rounded-2xl border border-sky-500/30 bg-sky-950/20 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-300">Loadout editor</p><p className="mt-1 text-sm text-slate-400">Change your identity whenever the next chapter calls for it.</p></div><button type="submit" disabled={busy || !name.trim()} className={BUTTON_PRIMARY}>{busy ? "Saving…" : "Save changes"}</button></div>
          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(180px,0.7fr)_1fr_1fr]">
            <input className={`${INPUT} bg-slate-950/60`} value={name} onChange={(event) => setName(event.target.value)} aria-label="Character name" maxLength={80} />
            <div className="flex flex-wrap gap-2">{AVATARS.map((item) => <button key={item.id} type="button" onClick={() => setAvatar(item.id)} className={`rounded-lg border px-2 py-1 text-xs ${avatar === item.id ? "border-sky-400 bg-sky-500/15 text-sky-200" : "border-slate-700 text-slate-400"} ${FOCUS_RING}`}>{item.title}</button>)}</div>
            <div className="flex flex-wrap gap-2">{ARCHETYPES.map((item) => <button key={item.id} type="button" onClick={() => setArchetype(item.id)} className={`rounded-lg border px-2 py-1 text-xs ${archetype === item.id ? "border-violet-400 bg-violet-500/15 text-violet-200" : "border-slate-700 text-slate-400"} ${FOCUS_RING}`}>{item.title}</button>)}</div>
          </div>
          <CustomizationPanel skinTone={skinTone} hairStyle={hairStyle} hairColor={hairColor} outfitColor={outfitColor} accessory={accessory} setSkinTone={setSkinTone} setHairStyle={setHairStyle} setHairColor={setHairColor} setOutfitColor={setOutfitColor} setAccessory={setAccessory} />
        </form>
      )}

      <section className="character-hero-panel mt-6 overflow-hidden rounded-[2rem] border border-slate-800/80 shadow-2xl shadow-sky-950/20" aria-labelledby="character-heading">
        <div className="character-hero-grid absolute inset-0" />
        <div className="relative grid min-h-[390px] lg:grid-cols-[0.9fr_1.1fr]">
          <div className="character-hero-stage flex items-end justify-center px-8 pt-10 sm:px-14 lg:items-center lg:pt-0">
            <div className="character-level-orbit" />
            <div className="relative z-10 flex flex-col items-center">
              <div className="character-hero-chip"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> ONLINE · LEARNING ARC ACTIVE</div>
              <CharacterSprite avatar={currentAvatar} archetype={currentArchetype.id} skinTone={skinTone} hairStyle={hairStyle} hairColor={hairColor} outfitColor={outfitColor} accessory={accessory} size="lg" animated className="mt-2" />
              <div className="-mt-2 rounded-full border border-slate-700/80 bg-slate-950/70 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 backdrop-blur">{currentArchetype.icon} {currentArchetype.title}</div>
            </div>
          </div>
          <div className="relative flex flex-col justify-center px-6 pb-8 pt-4 sm:px-12 lg:py-10">
            <div className="flex items-start justify-between gap-4"><div><p className="character-kicker">PLAYER CHARACTER · {currentAvatar.toUpperCase()}</p><h1 id="character-heading" className="mt-2 font-display text-4xl font-extrabold tracking-[-0.05em] text-white sm:text-5xl">{profile.character_name}</h1><p className="mt-2 max-w-md text-sm leading-relaxed text-slate-400">{currentArchetype.description} Your next ability is one good study session away.</p></div><div className="character-level-badge"><span>LVL</span><strong>{sheet.level}</strong></div></div>
            <div className="mt-8 max-w-lg"><LevelProgress sheet={sheet} /></div>
            <div className="mt-7 flex flex-wrap gap-2"><div className="character-mini-stat"><span className="text-amber-300">✦</span><span><strong>{streakLabel}</strong><small>study streak</small></span></div><div className="character-mini-stat"><span className="text-violet-300">◇</span><span><strong>{sheet.available_perk_points}</strong><small>perk points</small></span></div><div className="character-mini-stat"><span className="text-emerald-300">✓</span><span><strong>{achievementCount}/{totalAchievementCount}</strong><small>achievements</small></span></div></div>
          </div>
        </div>
      </section>

      <section className="mt-10" aria-labelledby="stats-heading">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="character-kicker">BUILD PROFILE</p><h2 id="stats-heading" className="mt-1 font-display text-xl font-bold text-white">Your learning stats</h2></div><p className="text-xs text-slate-500">Stats grow with every level and every comeback.</p></div>
        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">{statCards.map((stat) => <StatCard key={stat.key} label={stat.label} description={stat.description} value={stat.value} icon={stat.icon} color={stat.color} />)}</div>
      </section>

      <div className="mt-10 grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
        <section className="character-panel" aria-labelledby="perks-heading">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="character-kicker">ABILITY TREE</p><h2 id="perks-heading" className="mt-1 font-display text-xl font-bold text-white">Choose your perks</h2><p className="mt-1 text-xs text-slate-400">Shape how your learning adventure feels.</p></div><div className="character-points-badge"><span>{sheet.available_perk_points}</span> points available</div></div>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {sheet.perks.map((perk, index) => {
              const available = sheet.available_perk_points >= perk.cost;
              const unlocked = unlockedPerks.has(perk.id);
              return <article key={perk.id} className={`character-perk-card ${unlocked ? "character-perk-unlocked" : ""}`}><div className="flex items-start gap-3"><div className={`character-perk-node ${unlocked ? "character-perk-node-unlocked" : ""}`}><span>{unlocked ? "✓" : String(index + 1).padStart(2, "0")}</span></div><div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-2"><h3 className="text-sm font-semibold text-slate-100">{perk.title}</h3><span className={`text-[10px] font-semibold uppercase tracking-wider ${unlocked ? "text-emerald-300" : "text-slate-600"}`}>{unlocked ? "Active" : `Cost ${perk.cost}`}</span></div><p className="mt-1 text-xs leading-relaxed text-slate-400">{perk.description}</p></div></div>{!unlocked && <button type="button" disabled={busy || !available} onClick={() => void unlock(perk.id)} className={`mt-4 w-full rounded-lg border px-3 py-2 text-xs font-semibold transition ${available ? "border-violet-400/40 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20" : "cursor-not-allowed border-slate-800 bg-slate-950 text-slate-600"} ${FOCUS_RING}`}>{available ? "Unlock ability" : "Locked · level up to earn a point"}</button>}</article>;
            })}
          </div>
        </section>

        <section className="character-panel" aria-labelledby="achievements-heading">
          <div className="flex items-start justify-between gap-3"><div><p className="character-kicker">TROPHY CASE</p><h2 id="achievements-heading" className="mt-1 font-display text-xl font-bold text-white">Achievements</h2></div><span className="text-2xl text-amber-300" aria-hidden>✦</span></div>
          <div className="mt-6 space-y-3">
            {sheet.achievements.map((achievement) => { const percent = achievement.target > 0 ? Math.min(100, Math.round((achievement.progress / achievement.target) * 100)) : 0; return <article key={achievement.id} className={`character-achievement ${achievement.unlocked ? "character-achievement-unlocked" : ""}`}><div className="flex items-start gap-3"><div className={`character-achievement-icon ${achievement.unlocked ? "character-achievement-icon-unlocked" : ""}`}>{achievement.unlocked ? "✓" : "◇"}</div><div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-2"><h3 className="text-xs font-semibold text-slate-100">{achievement.title}</h3><span className={`text-[10px] font-semibold ${achievement.unlocked ? "text-emerald-300" : "text-slate-500"}`}>{achievement.unlocked ? "Earned" : `${achievement.progress}/${achievement.target}`}</span></div><p className="mt-1 text-[11px] leading-relaxed text-slate-400">{achievement.description}</p>{!achievement.unlocked && <div className="mt-2 h-1 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-amber-400" style={{ width: `${percent}%` }} /></div>}</div></div></article>; })}
          </div>
        </section>
      </div>

      <section className="character-next-step mt-5 flex flex-col gap-4 rounded-2xl border border-sky-500/20 bg-sky-950/20 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6"><div className="flex items-center gap-4"><div className="character-next-icon">→</div><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-300">Next mission</p><h2 className="mt-1 font-display text-lg font-bold text-white">Keep the arc moving.</h2><p className="mt-1 text-xs text-slate-400">Drill a skill or rescue one that is starting to fade.</p></div></div><div className="flex flex-wrap gap-2"><Link href="/quests" className={BUTTON_PRIMARY}>Open quests</Link><Link href="/courses" className={BUTTON_SECONDARY}>View courses</Link></div></section>
    </main>
  );
}
