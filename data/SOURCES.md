# Corpus provenance & licensing

Every file in `data/` is logged here (PROJECT_PLAN.md §7.5). Add a row in the same PR
that adds a file. Text files also carry a provenance header (title / source / license /
fetch date) as their first lines, which doubles as citation context for the LLM.

**Licenses in play**
- **PD** — Public domain (US federal government work, 17 U.S.C. §105). No restrictions.
- **OGL** — Open Government Licence v3.0. Reuse permitted with attribution:
  *"Contains public sector information licensed under the Open Government Licence v3.0,
  © Crown copyright, NHS."*

## data/pt/ — Physical Therapist corpus (fetched 2026-07-12)

| File | Source | License |
|---|---|---|
| medlineplus_sprains_and_strains.txt | https://medlineplus.gov/sprainsandstrains.html | PD |
| medlineplus_knee_injuries.txt | https://medlineplus.gov/kneeinjuriesanddisorders.html | PD |
| medlineplus_shoulder_injuries.txt | https://medlineplus.gov/shoulderinjuriesanddisorders.html | PD |
| medlineplus_ankle_injuries.txt | https://medlineplus.gov/ankleinjuriesanddisorders.html | PD |
| medlineplus_hip_injuries.txt | https://medlineplus.gov/hipinjuriesanddisorders.html | PD |
| medlineplus_back_pain.txt | https://medlineplus.gov/backpain.html | PD |
| medlineplus_neck_injuries.txt | https://medlineplus.gov/neckinjuriesanddisorders.html | PD |
| medlineplus_tendinitis.txt | https://medlineplus.gov/tendinitis.html | PD |
| medlineplus_rotator_cuff_injuries.txt | https://medlineplus.gov/rotatorcuffinjuries.html | PD |
| medlineplus_rehabilitation.txt | https://medlineplus.gov/rehabilitation.html | PD |
| medlineplus_sports_injuries.txt | https://medlineplus.gov/sportsinjuries.html | PD |
| medlineplus_knee_replacement.txt | https://medlineplus.gov/kneereplacement.html | PD |
| medlineplus_hip_replacement.txt | https://medlineplus.gov/hipreplacement.html | PD |
| medlineplus_exercise_older_adults.txt | https://medlineplus.gov/exerciseforolderadults.html | PD |
| medlineplus_dislocations.txt | https://medlineplus.gov/dislocations.html | PD |
| medlineplus_elbow_injuries.txt | https://medlineplus.gov/elbowinjuriesanddisorders.html | PD |
| medlineplus_foot_injuries.txt | https://medlineplus.gov/footinjuriesanddisorders.html | PD |
| niams_sports_injuries.txt | https://www.niams.nih.gov/health-topics/sports-injuries | PD |
| niams_back_pain.txt | https://www.niams.nih.gov/health-topics/back-pain | PD |
| ninds_pain.txt | https://www.ninds.nih.gov/health-information/disorders/back-pain (redirects to the NINDS "Pain" page — kept for pain-vs-soreness coverage) | PD |
| nia_three_types_of_exercise.txt | https://www.nia.nih.gov/health/exercise-and-physical-activity/three-types-exercise-can-improve-your-health-and-physical | PD |
| nhs_sprains_and_strains.txt | https://www.nhs.uk/conditions/sprains-and-strains/ | OGL |
| nhs_tendonitis.txt | https://www.nhs.uk/conditions/tendonitis/ | OGL |
| nhs_back_pain.txt | https://www.nhs.uk/conditions/back-pain/ | OGL |
| nhs_strength_flexibility.txt | https://www.nhs.uk/live-well/exercise/strength-and-flexibility-exercises/how-to-improve-strength-flexibility/ | OGL |
| nia_exercise_and_older_adults.pdf | https://order.nia.nih.gov/sites/default/files/2025-04/exercise-and-older-adults-nia_0.pdf | PD |
| cdc_steadi_stay_independent.pdf | https://www.cdc.gov/steadi/pdf/STEADI-Brochure-StayIndependent-508.pdf | PD |
| cdc_steadi_chair_rise_exercise.pdf | https://www.cdc.gov/steadi/pdf/STEADI-Brochure-ChairRiseEx-508.pdf | PD |
| cdc_steadi_what_you_can_do.pdf | https://www.cdc.gov/steadi/pdf/STEADI-Brochure-WhatYouCanDo-508.pdf | PD |

Fetch notes (2026-07-12): NIAMS redirected its sprains-and-strains / tendinitis / bursitis
topic URLs to the consolidated Sports Injuries fact sheet — only the one canonical copy is
kept here. MedlinePlus files contain only the `topic-summary` block (the rest of those
pages is link navigation, deliberately excluded).

**`data/pt/structured/` addition (audit pass, 2026-08-02):**

| File | Source | License |
|---|---|---|
| structured/Evidence-Based-Massage-Therapy.pdf | https://openlibrary-repo.ecampusontario.ca/jspui/bitstream/123456789/641/3/Evidence-Based-Massage-Therapy-1592410109._print.pdf | OER (eCampusOntario open textbook repository) |

This file was previously present but unlogged. Two other PDFs that were sitting alongside
it — an APTA conference sponsorship prospectus and an AOPT organizational strategic plan —
were removed in the same pass: they came from `src/scrapers/clinical_downloader.py`
indiscriminately downloading every PDF link off an AOPT clinical-guidelines page with no
relevance filtering, and are not clinical/educational content by any reasonable curation
standard for this project. Four `Geriatrics_*.pdf` files were also removed from this folder
as exact duplicates of files already logged above (`cdc_steadi_*`, `nia_exercise_and_older_adults.pdf`)
— `src/scrapers/jgpt_scraper.py` had copied them here under a different filename, which
would have caused the same content to be double-ingested into `pt_docs` (the folder-walk in
`rag_core.py` is now recursive).

**Still unresolved, flagged not fixed:** `data/pt/unstructured/*.txt` (10 files: Aerobic
Exercise, Endurance Exercise, Flexibility, Injury Prevention and Body Mechanics, Muscle,
Neuromotor Function, Physical Activity, Strength Training, Breathing Pattern Disorders,
Therapeutic Exercise) came from `src/scrapers/physiopedia_scraper.py`, which uses
`cloudscraper` specifically to bypass Physiopedia's Cloudflare bot protection.
Physiopedia's content is CC-BY-NC-SA (attribution required, non-commercial), and these
files carry no source URL/license/attribution at all. Whether to keep this content (and
if so, add proper attribution) or remove it is a licensing/ethics call for the team, not
made unilaterally here — see PROJECT_PLAN.md decision log.

## data/trainer/ — Gym Trainer corpus (fetched 2026-07-12)

| File | Source | License |
|---|---|---|
| cdc_pa_benefits.txt | https://www.cdc.gov/physical-activity-basics/benefits/index.html | PD |
| cdc_pa_guidelines_adults.txt | https://www.cdc.gov/physical-activity-basics/guidelines/adults.html | PD |
| cdc_pa_guidelines_older_adults.txt | https://www.cdc.gov/physical-activity-basics/guidelines/older-adults.html | PD |
| cdc_pa_measuring_intensity.txt | https://www.cdc.gov/physical-activity-basics/measuring/index.html | PD |
| cdc_pa_adding_activity.txt | https://www.cdc.gov/physical-activity-basics/adding-adults/index.html | PD |
| nia_get_started_exercise.txt | https://www.nia.nih.gov/health/exercise-and-physical-activity/how-older-adults-can-get-started-exercise | PD |
| medlineplus_exercise_and_fitness.txt | https://medlineplus.gov/exerciseandphysicalfitness.html | PD |
| medlineplus_how_much_exercise.txt | https://medlineplus.gov/howmuchexercisedoineed.html | PD |
| medlineplus_benefits_of_exercise.txt | https://medlineplus.gov/benefitsofexercise.html | PD |
| nhs_guidelines_adults_19_to_64.txt | https://www.nhs.uk/live-well/exercise/exercise-guidelines/physical-activity-guidelines-for-adults-aged-19-to-64/ | OGL |
| nhs_guidelines_older_adults.txt | https://www.nhs.uk/live-well/exercise/exercise-guidelines/physical-activity-guidelines-older-adults/ | OGL |
| nhs_strength_exercises.txt | https://www.nhs.uk/live-well/exercise/strength-and-flexibility-exercises/strength-exercises/ | OGL |
| nhs_balance_exercises.txt | https://www.nhs.uk/live-well/exercise/strength-and-flexibility-exercises/balance-exercises/ | OGL |
| nhs_flexibility_exercises.txt | https://www.nhs.uk/live-well/exercise/strength-and-flexibility-exercises/flexibility-exercises/ | OGL |
| nhs_sitting_exercises.txt | https://www.nhs.uk/live-well/exercise/strength-and-flexibility-exercises/sitting-exercises/ | OGL |
| nhs_gym_free_workouts.txt | https://www.nhs.uk/live-well/exercise/gym-free-workouts/ | OGL |
| nhs_couch_to_5k.txt | https://www.nhs.uk/live-well/exercise/running-and-aerobic-exercises/get-running-with-couch-to-5k/ | OGL |
| hhs_physical_activity_guidelines_2nd_ed.pdf | https://odphp.health.gov/sites/default/files/2019-09/Physical_Activity_Guidelines_2nd_edition.pdf | PD |
| odphp_move_your_way_older_adults.pdf | https://odphp.health.gov/sites/default/files/2023-08/PAG_MYW_FactSheet_OlderAdults-508c.pdf | PD |
| medlineplus_exercise_older_adults.txt | *(shared with data/pt/ — same file, both agents need it)* | PD |
| nia_three_types_of_exercise.txt | *(shared with data/pt/)* | PD |
| nia_exercise_and_older_adults.pdf | *(shared with data/pt/)* | PD |

Fetch notes (2026-07-12): US Army FM 7-22 was dropped — armypubs.army.mil blocks scripted
downloads (returns an HTML wall instead of the PDF); corpus meets the target without it.
Three files are deliberately duplicated from `data/pt/` because collections are siloed per
agent (decision D3) and the "elderly getting active" persona needs them in BOTH knowledge
bases. Move Your Way fact sheets moved to `/2023-08/PAG_MYW_FactSheet_*-508c.pdf` URLs
(the 2019 URLs 404); the adults variant still 404s and was skipped.

## data/surgeon/ — Orthopedic Surgeon corpus (fetched 2026-07-14)

| File | Source | License |
|---|---|---|
| medlineplus_surgical_wound_care_open.txt | https://medlineplus.gov/ency/patientinstructions/000040.htm | PD |
| medlineplus_surgical_wound_care_closed.txt | https://medlineplus.gov/ency/patientinstructions/000738.htm | PD |
| medlineplus_surgical_wound_infection.txt | https://medlineplus.gov/ency/article/007645.htm | PD |
| medlineplus_how_wounds_heal.txt | https://medlineplus.gov/ency/patientinstructions/000741.htm | PD |
| medlineplus_sutures_staples_at_home.txt | https://medlineplus.gov/ency/patientinstructions/000498.htm | PD |
| medlineplus_using_crutches.txt | https://medlineplus.gov/ency/patientinstructions/000344.htm | PD |
| medlineplus_acl_reconstruction.txt | https://medlineplus.gov/ency/article/007208.htm | PD |
| medlineplus_acl_reconstruction_discharge.txt | https://medlineplus.gov/ency/patientinstructions/000189.htm | PD |
| medlineplus_rotator_cuff_repair.txt | https://medlineplus.gov/ency/article/007207.htm | PD |
| medlineplus_hardware_removal.txt | https://medlineplus.gov/ency/article/007644.htm | PD |
| medlineplus_knee_arthroscopy.txt | https://medlineplus.gov/ency/article/002972.htm | PD |
| medlineplus_knee_arthroscopy_discharge.txt | https://medlineplus.gov/ency/patientinstructions/000199.htm | PD |
| medlineplus_getting_home_ready.txt | https://medlineplus.gov/ency/patientinstructions/000167.htm | PD |
| medlineplus_knee_joint_replacement_discharge.txt | https://medlineplus.gov/ency/patientinstructions/000170.htm | PD |
| niams_hip_replacement_surgery.txt | https://www.niams.nih.gov/health-topics/hip-replacement-surgery | PD |
| nhs_hip_replacement_recovery.txt | https://www.nhs.uk/tests-and-treatments/hip-replacement/recovering-from-a-hip-replacement/ | OGL |
| nhs_knee_replacement_recovery.txt | https://www.nhs.uk/tests-and-treatments/knee-replacement/recovery/ | OGL |
| nhs_having_surgery_recovery.txt | https://www.nhs.uk/tests-and-treatments/having-surgery/recovery/ | OGL |

Fetch notes (2026-07-14): these are all "encyclopedia / patient-instructions" style
MedlinePlus pages (procedure and discharge-care specific), deliberately distinct from the
`kneereplacement.html` / `hipreplacement.html` "topic-summary" pages already used in
`data/pt/` — no duplication between the two corpora. Two candidate URLs 403'd the fetcher
and were dropped rather than retried: `cdc.gov/surgical-site-infections/about/index.html`
(CDC's patient SSI-basics page) and NIAMS's `community-outreach-initiative/.../
joint-replacement-surgery` overview page; `medlineplus_surgical_wound_infection.txt` and
`niams_hip_replacement_surgery.txt` cover the same ground so the corpus wasn't short-changed.
Only `nhs.uk` main-domain pages were used for NHS content (not individual NHS Trust
subdomains like `guysandstthomas.nhs.uk`, which are separate legal entities not
necessarily under the same OGL terms) — consistent with the PT/trainer corpora.

---

## data/nutrition/ — Sports Nutritionist corpus (fetched 2026-07-30)

| File | Source | License |
|---|---|---|
| nih_ods_calcium.md | https://ods.od.nih.gov/factsheets/Calcium-Consumer/ | PD |
| nih_ods_exercise_and_athletic_performance.md | https://ods.od.nih.gov/factsheets/ExerciseAndAthleticPerformance-Consumer/ | PD |
| nih_ods_omega3.md | https://ods.od.nih.gov/factsheets/Omega3FattyAcids-Consumer/ | PD |
| nih_ods_vitamin_c.md | https://ods.od.nih.gov/factsheets/VitaminC-Consumer/ | PD |
| nih_ods_vitamin_d.md | https://ods.od.nih.gov/factsheets/VitaminD-Consumer/ | PD |
| nih_ods_zinc.md | https://ods.od.nih.gov/factsheets/Zinc-Consumer/ | PD |
| medlineplus_diet_and_wound_healing.md | https://medlineplus.gov/ency/article/002458.htm | PD |
| medlineplus_minerals.md | https://medlineplus.gov/ency/article/002467.htm | PD |
| medlineplus_protein_in_diet.md | https://medlineplus.gov/ency/article/002470.htm | PD |
| medlineplus_vitamins.md | https://medlineplus.gov/ency/article/002404.htm | PD |

All 10 text files are US federal government sources (NIH Office of Dietary Supplements,
MedlinePlus) — public domain, same convention as the rest of this project. Two independent
passes added this section (an audit pass on 2026-08-02 and the persistence branch on
2026-07-31, which is why an earlier draft said "nine"); the table above is the merged,
de-duplicated list and matches the 10 files actually on disk.

Fetch notes: unlike the other three corpora, this one is **scraper-built rather than
hand-curated** — `python -m src.ingest --agent nutrition --scrape` runs
`src/scrapers/nutrition_scraper.py`, which fetches the pages above and writes each one with
an HTML provenance comment (`Source`, `Title`, `Scraped At`) as its first lines. The rows in
this table were reconstructed from those headers, so they are the fetcher's own record rather
than a hand-typed list. NIH ODS uses the *Consumer* fact sheets (plain-language,
patient-facing) rather than the Health Professional versions, and the MedlinePlus pages are
encyclopedia articles. No OGL/NHS content here. The files were fetched 2026-07-30 with the
nutritionist agent but were not logged in this ledger until 2026-08-02, which broke §7.5 in
the meantime.

Known wart, deliberately not cleaned up: the scraper keeps the pages' site navigation
boilerplate (menus, "official website of the United States government" banners) in the saved
markdown, so some chunks are navigation text rather than nutrition content. It degrades
retrieval precision slightly but never correctness — the grounding rule means a junk chunk
just doesn't get used.

---

## data/*/visuals/ — Visual assets for CLIP multimodal search

Not logged per file. These folders hold **288 image files** (pt 114, trainer 163, surgeon 9,
nutrition 2) feeding the CLIP visual search (`src/multimodal/clip_search.py`), which embeds
the readable subset of them — see the 2026-08-02 vision results block in PROJECT_PLAN.md for
the indexed count. They come from two automated sources:

| Source | Produced by | License basis |
|---|---|---|
| Wikimedia Commons API queries (Blausen Medical anatomy plates, joint/ROM diagrams, exercise-form illustrations, USDA MyPlate & food-pyramid graphics) | `src/scrapers/{surgeon,pt,trainer,nutrition}_media_scraper.py` | free license required by Commons, but **not verified per file** — see below |
| Figures extracted from the PDFs already in `data/*/` | `src/scrapers/pdf_image_extractor.py` | inherits the parent PDF's license (all PD — see the corpus tables above) |

**Open item, flagged as a real gap rather than resolved here.** The media scrapers query the
Commons search API for terms like "MyPlate" or "rotator cuff" and download whatever comes back
with an `image/*` mime type, so **no individual image's license was manually verified**.
Commons requires every hosted file to carry *some* free license, but they vary (PD/CC0, CC-BY,
CC-BY-SA) and their reuse terms differ. That is tolerable while the images only ever render
inside the app; it is not tolerable in a deliverable. **Any image reproduced in the written
report, slides, or video needs its Commons page checked and attributed first** — CC-BY-SA
needs a credit line, and the file names (e.g. `Blausen_0597_KneeAnatomy_Side.png`) are enough
to find the source page.

Housekeeping note (2026-08-02 audit pass): two byte-identical duplicate images in
`data/nutrition/visuals/` were found by checksum and removed, which is why that folder holds
2 files rather than the 4 an earlier draft of this section counted.
