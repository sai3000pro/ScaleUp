"use client";

import type {
  CharacterAccessory,
  CharacterArchetype,
  CharacterAvatar,
  CharacterHairColor,
  CharacterHairStyle,
  CharacterOutfitColor,
  CharacterSkinTone,
} from "@/lib/types";

type SpriteSize = "sm" | "md" | "lg";

interface CharacterSpriteProps {
  avatar: CharacterAvatar;
  archetype: CharacterArchetype;
  skinTone?: CharacterSkinTone;
  hairStyle?: CharacterHairStyle;
  hairColor?: CharacterHairColor;
  outfitColor?: CharacterOutfitColor;
  accessory?: CharacterAccessory;
  size?: SpriteSize;
  animated?: boolean;
  className?: string;
}

const PALETTE: Record<CharacterAvatar, { primary: string; secondary: string; accent: string; skin: string; hair: string }> = {
  owl: { primary: "#38bdf8", secondary: "#0f4c81", accent: "#fbbf24", skin: "#d8b08c", hair: "#f8fafc" },
  fox: { primary: "#fb923c", secondary: "#9a3412", accent: "#facc15", skin: "#f2bd91", hair: "#7c2d12" },
  robot: { primary: "#a78bfa", secondary: "#4c1d95", accent: "#34d399", skin: "#cbd5e1", hair: "#64748b" },
  wizard: { primary: "#c084fc", secondary: "#581c87", accent: "#f0abfc", skin: "#f0c3a0", hair: "#312e81" },
  cat: { primary: "#2dd4bf", secondary: "#115e59", accent: "#f9a8d4", skin: "#e8b994", hair: "#475569" },
  dragon: { primary: "#f43f5e", secondary: "#881337", accent: "#fb923c", skin: "#c98f7a", hair: "#4c0519" },
};

const SKIN_PALETTE: Record<CharacterSkinTone, string> = {
  moon: "#f3d0b5",
  sand: "#d8b08c",
  honey: "#b9784d",
  copper: "#8f4e38",
  ebony: "#59352d",
};

const HAIR_PALETTE: Record<CharacterHairColor, string> = {
  ink: "#172033",
  chestnut: "#7c2d12",
  silver: "#cbd5e1",
  violet: "#5b21b6",
  rose: "#be185d",
};

const OUTFIT_PALETTE: Record<CharacterOutfitColor, { primary: string; secondary: string }> = {
  azure: { primary: "#38bdf8", secondary: "#0f4c81" },
  violet: { primary: "#a78bfa", secondary: "#4c1d95" },
  coral: { primary: "#fb7185", secondary: "#9f1239" },
  mint: { primary: "#34d399", secondary: "#115e59" },
  gold: { primary: "#fbbf24", secondary: "#92400e" },
};

const SIZE_CLASS: Record<SpriteSize, string> = {
  sm: "h-20 w-20",
  md: "h-32 w-32",
  lg: "h-56 w-56 sm:h-64 sm:w-64",
};

function Ears({ avatar, fill, stroke }: { avatar: CharacterAvatar; fill: string; stroke: string }) {
  if (avatar === "robot") {
    return (
      <>
        <rect x="57" y="98" width="13" height="42" rx="6" fill={stroke} />
        <rect x="170" y="98" width="13" height="42" rx="6" fill={stroke} />
        <circle cx="63" cy="93" r="9" fill={fill} stroke={stroke} strokeWidth="5" />
        <circle cx="177" cy="93" r="9" fill={fill} stroke={stroke} strokeWidth="5" />
      </>
    );
  }

  if (avatar === "wizard") {
    return <path d="M61 94 L77 40 L99 94 Z M141 94 L164 40 L180 94 Z" fill={fill} stroke={stroke} strokeWidth="6" strokeLinejoin="round" />;
  }

  if (avatar === "dragon") {
    return <path d="M62 102 L45 57 L83 78 L101 99 Z M138 99 L157 78 L195 57 L178 102 Z" fill={fill} stroke={stroke} strokeWidth="6" strokeLinejoin="round" />;
  }

  if (avatar === "owl") {
    return (
      <>
        <circle cx="80" cy="91" r="34" fill={fill} stroke={stroke} strokeWidth="6" />
        <circle cx="160" cy="91" r="34" fill={fill} stroke={stroke} strokeWidth="6" />
      </>
    );
  }

  return <path d="M59 104 L56 45 L103 82 Z M137 82 L184 45 L181 104 Z" fill={fill} stroke={stroke} strokeWidth="6" strokeLinejoin="round" />;
}

function Hair({ style, color }: { style: CharacterHairStyle; color: string }) {
  if (style === "curls") {
    return <path d="M78 119 Q73 91 91 86 Q101 68 117 82 Q133 67 146 84 Q168 86 161 119 Q145 103 120 112 Q95 103 78 119 Z" fill={color} stroke="#1e293b" strokeWidth="6" strokeLinejoin="round" />;
  }
  if (style === "bob") {
    return <path d="M73 128 Q67 77 120 75 Q173 77 167 128 L151 119 L145 91 Q120 103 95 91 L89 119 Z" fill={color} stroke="#1e293b" strokeWidth="6" strokeLinejoin="round" />;
  }
  if (style === "mohawk") {
    return <path d="M88 117 Q84 92 97 87 L103 51 L114 74 L122 40 L131 74 L145 53 L149 88 Q157 94 152 117 Q136 104 120 111 Q104 104 88 117 Z" fill={color} stroke="#1e293b" strokeWidth="6" strokeLinejoin="round" />;
  }
  if (style === "crown") {
    return <path d="M78 116 Q74 83 93 78 L102 48 L120 70 L138 48 L147 78 Q166 83 162 116 Q143 103 120 111 Q97 103 78 116 Z" fill={color} stroke="#1e293b" strokeWidth="6" strokeLinejoin="round" />;
  }
  return <path d="M76 104 Q120 72 164 104 L159 133 Q120 112 81 133 Z" fill={color} stroke="#1e293b" strokeWidth="6" strokeLinejoin="round" />;
}

function Face({ avatar, skin, hair, hairStyle, accent }: { avatar: CharacterAvatar; skin: string; hair: string; hairStyle: CharacterHairStyle; accent: string }) {
  const isRobot = avatar === "robot";
  const isOwl = avatar === "owl";

  return (
    <>
      <path d="M75 108 Q120 83 165 108 L165 151 Q156 184 120 190 Q84 184 75 151 Z" fill={skin} stroke="#1e293b" strokeWidth="6" />
      {isRobot ? (
        <>
          <rect x="81" y="113" width="78" height="57" rx="16" fill="#94a3b8" stroke="#1e293b" strokeWidth="6" />
          <circle cx="102" cy="139" r="7" fill={accent} />
          <circle cx="138" cy="139" r="7" fill={accent} />
          <path d="M103 157 Q120 166 137 157" fill="none" stroke="#1e293b" strokeWidth="5" strokeLinecap="round" />
        </>
      ) : isOwl ? (
        <>
          <circle cx="101" cy="137" r="23" fill="#f8fafc" stroke="#1e293b" strokeWidth="5" />
          <circle cx="139" cy="137" r="23" fill="#f8fafc" stroke="#1e293b" strokeWidth="5" />
          <circle cx="101" cy="137" r="8" fill="#1e293b" />
          <circle cx="139" cy="137" r="8" fill="#1e293b" />
          <path d="M112 151 L120 162 L128 151" fill={accent} stroke="#1e293b" strokeWidth="4" strokeLinejoin="round" />
        </>
      ) : (
        <>
          <Hair style={hairStyle} color={hair} />
          <circle cx="102" cy="139" r="6" fill="#1e293b" />
          <circle cx="138" cy="139" r="6" fill="#1e293b" />
          <path d="M108 158 Q120 166 132 158" fill="none" stroke="#1e293b" strokeWidth="5" strokeLinecap="round" />
        </>
      )}
    </>
  );
}

export function CharacterSprite({
  avatar,
  archetype,
  skinTone = "sand",
  hairStyle = "sweep",
  hairColor = "chestnut",
  outfitColor = "azure",
  accessory = "none",
  size = "md",
  animated = false,
  className = "",
}: CharacterSpriteProps) {
  const baseColors = PALETTE[avatar] ?? PALETTE.owl;
  const outfit = OUTFIT_PALETTE[outfitColor] ?? OUTFIT_PALETTE.azure;
  const colors = { ...baseColors, ...outfit, skin: SKIN_PALETTE[skinTone] ?? SKIN_PALETTE.sand, hair: HAIR_PALETTE[hairColor] ?? HAIR_PALETTE.chestnut };
  const spriteId = `sprite-${avatar}-${archetype}-${skinTone}-${hairStyle}-${hairColor}-${outfitColor}-${accessory}-${size}`;

  return (
    <div className={`${SIZE_CLASS[size]} relative shrink-0 ${animated ? "character-sprite-float" : ""} ${className}`} aria-label={`${archetype} ${avatar} character`} role="img">
      <svg viewBox="0 0 240 280" className="h-full w-full overflow-visible" aria-hidden="true">
        <defs>
          <radialGradient id={`${spriteId}-halo`} cx="50%" cy="45%" r="60%">
            <stop offset="0%" stopColor={colors.primary} stopOpacity=".34" />
            <stop offset="72%" stopColor={colors.secondary} stopOpacity=".12" />
            <stop offset="100%" stopColor={colors.secondary} stopOpacity="0" />
          </radialGradient>
          <linearGradient id={`${spriteId}-cloak`} x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor={colors.primary} />
            <stop offset="100%" stopColor={colors.secondary} />
          </linearGradient>
        </defs>
        <circle cx="120" cy="137" r="116" fill={`url(#${spriteId}-halo)`} />
        <ellipse cx="120" cy="257" rx="65" ry="10" fill="#020617" opacity=".55" />
        <path d="M57 254 Q62 193 91 177 Q120 164 149 177 Q178 193 183 254 Z" fill={`url(#${spriteId}-cloak)`} stroke="#1e293b" strokeWidth="7" />
        <path d="M92 183 Q120 203 148 183 L139 254 L101 254 Z" fill="#f8fafc" opacity=".92" />
        <path d="M120 191 L129 211 L120 221 L111 211 Z" fill={colors.accent} stroke="#1e293b" strokeWidth="4" />
        <path d="M91 205 Q72 221 63 246" fill="none" stroke={colors.primary} strokeWidth="15" strokeLinecap="round" />
        <path d="M149 205 Q168 221 177 246" fill="none" stroke={colors.primary} strokeWidth="15" strokeLinecap="round" />
        <Ears avatar={avatar} fill={colors.primary} stroke="#1e293b" />
        <Face avatar={avatar} skin={colors.skin} hair={colors.hair} hairStyle={hairStyle} accent={colors.accent} />
        {accessory === "glasses" && <path d="M78 134 H112 Q120 134 128 134 H162 M94 134 Q94 151 105 151 Q116 151 116 134 M124 134 Q124 151 135 151 Q146 151 146 134" fill="none" stroke="#f8fafc" strokeWidth="4" strokeLinecap="round" />}
        {accessory === "headband" && <path d="M73 111 Q120 77 167 111" fill="none" stroke={colors.accent} strokeWidth="8" strokeLinecap="round" />}
        {accessory === "crown" && <path d="M91 83 L99 57 L120 75 L141 57 L149 83 Z" fill={colors.accent} stroke="#1e293b" strokeWidth="5" strokeLinejoin="round" />}
        {accessory === "earring" && <><circle cx="76" cy="163" r="6" fill={colors.accent} stroke="#1e293b" strokeWidth="3" /><circle cx="164" cy="163" r="6" fill={colors.accent} stroke="#1e293b" strokeWidth="3" /></>}
        {archetype === "scholar" && <path d="M76 122 H52 Q47 122 47 128 V148 Q47 154 52 154 H76 M164 122 H188 Q193 122 193 128 V148 Q193 154 188 154 H164" fill="none" stroke={colors.accent} strokeWidth="5" />}
        {archetype === "builder" && <path d="M91 201 L79 219 L91 233 M149 201 L161 219 L149 233" fill="none" stroke={colors.accent} strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />}
        {archetype === "explorer" && <path d="M177 191 L194 200 L185 216 L168 207 Z" fill={colors.accent} stroke="#1e293b" strokeWidth="4" />}
        {archetype === "mentor" && <path d="M70 217 Q62 205 72 195 M170 217 Q178 205 168 195" fill="none" stroke={colors.accent} strokeWidth="6" strokeLinecap="round" />}
      </svg>
    </div>
  );
}

export function avatarLabel(avatar: CharacterAvatar): string {
  return avatar.charAt(0).toUpperCase() + avatar.slice(1);
}
