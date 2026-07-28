/**
 * TypeScript mirrors of the JSON Schemas in /contracts.
 *
 * These are hand-written rather than generated. If you change a contract,
 * change these too -- nothing enforces the correspondence at build time, which
 * is a known gap. The Python validator is the actual source of truth.
 */

export type DamageClass = "intact" | "damaged";

export interface DamageFeature {
  type: "Feature";
  id?: number | string;
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: number[][][] };
  properties: {
    building_id: number;
    damage_class: DamageClass;
    obscured: boolean;
    area_m2: number | null;
    grid_cell_id?: string;
  };
}

export interface DamageLayer {
  type: "FeatureCollection";
  groundtruth: {
    contract_version: string;
    event_id: string;
    generated_at: string;
    crs: "EPSG:4326";
    /**
     * Sensor-agnostic provenance. Discriminated on `tool`: HASTE (optical) or
     * Sentinel-1 SAR. The fusion engine never reads this — it's for the audit
     * trail — so consumers must narrow on `tool` before touching sensor fields.
     */
    source:
      | {
          tool: "haste";
          haste_commit: string;
          workflow?: "building" | "standard";
          backbone: string;
          num_features?: number;
          resize_factor?: number;
          footprint_source?: string;
          imagery_note?: string;
        }
      | {
          tool: "sentinel1_sar";
          sensor: string;
          classifier: string;
          classifier_ref?: string;
          baseline_window?: [string, string];
          target_window?: [string, string];
          flood_fraction_threshold?: number;
          footprint_source: string;
          footprint_confidence_min?: number;
          imagery_note?: string;
        };
    /** Absent when nothing was validated. Do NOT invent values to fill it. */
    accuracy?: {
      labels_total?: number;
      labels_damaged?: number;
      validation_sample_n?: number;
      damaged_precision?: number;
      damaged_recall?: number;
      damaged_f1?: number;
      overall_accuracy?: number;
      estimated_damaged_total?: number;
      estimated_damaged_ci95?: [number, number];
    };
    counts?: {
      buildings_total: number;
      buildings_damaged: number;
      buildings_obscured: number;
    };
    notes?: string;
  };
  features: DamageFeature[];
}

export type Tier = "corroborated" | "plausible_unverified" | "suspect";
export type Urgency = "critical" | "high" | "medium" | "low";
export type SpatialStatus =
  | "consistent"
  | "contradicted"
  | "no_coverage"
  | "not_applicable";
export type VlmStatus = "supports" | "contradicts" | "inconclusive";

export type EventType =
  | "flood_inundation"
  | "structural_damage"
  | "road_blocked"
  | "people_stranded"
  | "medical_need"
  | "water_food_need"
  | "power_outage"
  | "shelter_status"
  | "missing_person"
  | "other";

/**
 * Telegram photo upload reference. Live tips (citizen_telegram) carry this
 * shape inside raw.media_refs; the audit drawer renders a thumbnail at
 * console/public/data/{photo_path}.
 */
export interface TelegramPhotoRef {
  photo_path: string;
  received_at?: string;
}

export interface VlmAssessment {
  status: VlmStatus;
  model: string | null;
  description: string;
  assessed_at: string;
}

export interface Signal {
  contract_version?: string;
  signal_id: string;
  channel: "citizen_seed" | "citizen_telegram" | "vlm_imagery" | "vlm_photo";
  source: {
    source_id: string;
    platform?: string;
    author_ref?: string | null;
    url?: string | null;
    received_at: string;
    replay_offset_s?: number | null;
  };
  raw?: {
    text?: string | null;
    lang?: "bn" | "en" | "bn-latn" | "mixed" | "unknown";
    /**
     * Backward-compatible: seeded imagery rows use strings; live Telegram
     * photo tips carry { photo_path, received_at } objects (see
     * DECISIONS.md D-029 and contracts/signal.schema.json).
     */
    media_refs?: Array<string | TelegramPhotoRef>;
    imagery_ref?: string | null;
  };
  claim: {
    location_ref: string;
    event_type: EventType;
    urgency: Urgency;
    persons_at_risk: number | null;
    claimed_time: string | null;
    needs?: string[];
    summary_en?: string;
  };
  geo: {
    lon: number;
    lat: number;
    grid_cell_id?: string;
    geocode: {
      method: string;
      matched_name: string;
      admin?: string;
      score: number;
      ambiguous?: boolean;
      candidates?: {
        name: string;
        admin?: string;
        score: number;
        lon?: number;
        lat?: number;
      }[];
    };
  } | null;
  verification: {
    tier: Tier;
    reason: string;
    corroborating_signal_ids?: string[];
    distinct_source_count?: number;
    spatial_check?: {
      status: SpatialStatus;
      inside_valid_area?: boolean;
      buildings_in_radius?: number;
      damaged_in_radius?: number;
      radius_m?: number;
    };
    fusion_weight: number;
    recon_priority?: boolean;
    verified_at?: string;
    /**
     * Photo-channel VLM result. Modulates trust after spatial verification;
     * never overrides. Absent for non-photo tips and for tips where no model
     * was callable (see bot/vlm_check.py).
     */
    vlm_assessment?: VlmAssessment;
  };
  extraction?: {
    model?: string;
    prompt_version?: string;
    extracted_at?: string;
    confidence?: number | null;
    cached?: boolean;
  };
  /**
   * Planted-fake ground truth. Present only in the seeded dataset.
   * The UI may display it as a teaching aid, but NOTHING that computes a tier,
   * a weight, or a score may read it. See DECISIONS.md D-010.
   */
  eval?: {
    planted_fake?: boolean;
    fake_kind?: string;
    expected_tier?: Tier;
    provenance_note?: string;
  };
}

export interface SectorCell {
  cell_id: string;
  centroid: { lon: number; lat: number };
  bbox?: [number, number, number, number] | number[];
  rank?: number;
  score: number;
  components: {
    damage: number | null;
    vlm: number | null;
    citizen: number | null;
  };
  coverage?: {
    in_valid_area?: boolean;
    buildings_obscured?: number;
    status?: "assessed" | "partial" | "unassessed";
  };
  evidence: {
    buildings_total?: number;
    buildings_damaged?: number;
    damaged_fraction?: number | null;
    damaged_area_m2?: number | null;
    signal_ids?: string[];
    corroborated_count?: number;
    plausible_unverified_count?: number;
    suspect_count?: number;
    distinct_source_count?: number;
    vlm_finding_ids?: string[];
  };
  urgency_max?: Urgency | null;
  persons_at_risk_est?: number | null;
  top_reasons?: string[];
  place_label?: string | null;
  updated_at?: string;
}

export interface SectorScores {
  contract_version: string;
  event_id: string;
  generated_at: string;
  grid: { cell_size_m: number; scheme: string; origin?: number[] };
  weights: {
    damage: number;
    vlm: number;
    citizen: number;
    tier_multipliers?: Record<string, number>;
    urgency_multipliers?: Record<Urgency, number>;
  };
  cells: SectorCell[];
}

export interface ValidArea {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    properties: Record<string, unknown>;
    geometry: { type: "Polygon"; coordinates: number[][][] };
  }[];
}
