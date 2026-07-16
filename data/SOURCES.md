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
