# Privacy, lawful basis and data handling

This system performs **biometric identification of individuals by a fixed camera**. That is the
most legally sensitive configuration in this codebase, and the documentation is part of the
build, not an afterthought. Read this before pointing a camera at anyone.

Nothing here is legal advice. It sets out what the software does, what it stores, and what the
operator must decide and document before deployment.

---

## 1. What is collected

| Data | Where | Notes |
|---|---|---|
| Face template (512-d vector) | `enrollments.embedding_encrypted` | **Encrypted at rest.** Derived from enrolment photos; the photos themselves are not stored. |
| Face crops (112×112 thumbnails) | `var/thumbs/*.jpg`, referenced from `sightings` / `unknown_sightings` | Evidence for the review queue. Auto-deleted — see §4. |
| Sightings | `sightings` | Timestamps, confidence, quality, occlusion ratio, track id. No imagery beyond the thumbnail pointer. |
| Attendance records | `attendance_records` | Derived. The academic/employment record. |
| Account data | `users` | Name, username, roll number, email, password hash, consent flag and timestamp. |
| Audit log | `audit_log` | Every override, export, unknown-face assignment, consent change and biometric deletion. |

**A face template is not like a password.** If a password database leaks, everyone rotates their
password. If a template database leaks, the subject cannot rotate their face — the compromise is
permanent and follows them to every other system that uses face recognition. This is why the
embedding column is encrypted with a key held outside the database
(`ATTENDANCE_FERNET_KEY`), and why `ATTENDANCE_ENV=production` refuses to start without one.

The encryption here protects against a stolen database file. It is **not** biometric template
protection in the cryptographic sense (cancellable biometrics, fuzzy vaults, homomorphic
matching). The upstream architecture document lists that as an unimplemented hook.

---

## 2. Lawful basis and consent (India, DPDP Act 2023)

The Digital Personal Data Protection Act 2023 governs deployment in India. The operator is the
**Data Fiduciary**; enrolled people are **Data Principals**.

What the software enforces:

- **Consent is explicit and recorded.** `users.consent_given` + `users.consent_at` +
  `consent_text_version`. With `attendance.require_consent: true` (the default), enrolment is
  refused with HTTP 403 when consent is absent. There is no path that captures a template first
  and asks later.
- **Consent is withdrawable.** `POST /api/me/consent {consent_given: false}`, and
  `DELETE /api/users/{id}/biometrics` destroys the template and every stored crop.
- **Every consequential action is logged**, with a mandatory free-text reason on overrides.

What the operator must do, and the software cannot do for you:

1. **Publish a notice** before collection, in English and the languages the DPDP Act requires,
   stating the purpose (attendance), the data collected, the retention period, and how to
   withdraw consent and complain.
2. **Appoint a contact** for Data Principal requests and publish the address.
3. **Handle minors.** The DPDP Act requires verifiable parental consent for anyone under 18 and
   prohibits tracking or behavioural monitoring of children. *A school deployment is therefore a
   materially different legal proposition from a college one.* This software has no parental
   consent workflow — you must build or operate one outside it.
4. **Post camera signage** at every entrance to a monitored space (see §5).
5. **Report breaches** to the Data Protection Board and to affected people.

If you deploy in the EU, continuous biometric identification also engages the EU AI Act and
GDPR Art. 9 special-category rules; the upstream architecture document §0 covers that ground.

---

## 3. Purpose limitation

The templates in this system exist to mark attendance. They must not be used to:

- track movement or dwell time for any purpose other than the presence rule the session declares;
- infer emotion, attentiveness, demographics or behaviour;
- populate a watchlist, or be shared with any third party or law-enforcement body absent a lawful
  order;
- seed any other face-recognition system.

The schema deliberately does not carry fields for any of these.

---

## 4. Retention

Configured by `attendance.retention_days` (default **30**), applied by
`POST /api/admin/retention` (admin only, audit-logged). Run it on a schedule.

The rule: **attendance survives, biometrics do not.**

- Face crops and their DB pointers are deleted once older than the retention window.
- `sightings` and `attendance_records` are kept — a student may need them months later to
  dispute a grade, and an employee to dispute pay.
- Templates persist while the person is enrolled and consent stands, and are destroyed on
  erasure or consent withdrawal.

Set `attendance.store_thumbnails: false` to keep no imagery at all. The review queue then shows
scores and timings without a face crop, which is less useful for a human check but stores less.

---

## 5. Camera signage

Every entrance to a monitored space needs a visible sign, before the camera's field of view,
carrying at minimum:

> **Facial-recognition attendance in operation.**
> Purpose: recording attendance for scheduled sessions.
> Operator: `<organisation>` · Contact: `<email / office>`
> Face images are retained `<N>` days. You may withdraw consent and request deletion at
> `<link>`. A non-biometric alternative is available — ask at `<office>`.

---

## 6. Non-biometric fallback — required

**Anyone who declines biometric enrolment must still be able to be marked present, without
penalty and without having to explain themselves.** Consent that costs you your attendance is
not freely given, and a system that offers no alternative is coercive regardless of what the
consent checkbox says.

The software supports this today:

- A student who never enrols is simply never matched. They appear as `absent`, and faculty mark
  them present through `PATCH /api/attendance/{id}` with a reason — a normal, audit-logged
  override, not an exception path.
- `POST /api/me/corrections` lets a person dispute any record; it opens a request for a human
  and never edits attendance automatically.

The operator must define and publish the concrete fallback — a roll call, a signed register, a
card tap — and must not make it more burdensome than the biometric path.

---

## 7. Rights of the individual

| Right | How |
|---|---|
| Access | `GET /api/me/attendance` — the full personal record. |
| Correction | `POST /api/me/corrections` — routed to a human. |
| Erasure | `DELETE /api/users/{id}/biometrics` — templates and crops destroyed, FAISS index rebuilt, attendance retained. |
| Withdraw consent | `POST /api/me/consent` — blocks further enrolment; pair with erasure. |

A student can only ever read their own rows; this is enforced in the query and covered by
`tests/test_authorization.py`.

---

## 8. Known limitations that carry privacy weight

These are stated plainly because deploying without knowing them would be irresponsible.

1. **Anti-spoofing ships with no weights.** `occlubio/pipeline/antispoof.py` is a hook. Without a
   MiniFASNet ONNX at `antispoof.onnx_path`, `check()` returns `live=True` for everything —
   including a phone screen held up to the lens. The default `antispoof_mode: strict` makes a
   live camera **refuse to start** in that state. Setting it to `permissive` accepts that anyone
   can be impersonated with a photograph.
2. **Thresholds are unvalidated.** The shipped `match_threshold` / `review_threshold` /
   `dup_threshold` are the build spec's placeholder numbers, not values derived from a ROC curve
   on enrolled faces. Until `tools/roc.py` has been run on real identities, the false-accept and
   false-reject rates of this deployment are **unknown**. A false accept marks the wrong person
   present; a false reject marks a present person absent.
3. **Demographic bias is unmeasured.** Face recognition accuracy varies across skin tone, age
   and gender, and `buffalo_l` was not trained on your population. Attendance is consequential,
   so measure error rates per demographic group before relying on it, and keep the review queue
   staffed. `tools/roc.py` reports aggregate numbers only — it does not slice by demographic,
   because that requires labels this system deliberately does not collect.
4. **Occlusion estimation is heuristic.** `occlusion.py` uses skin-tone ratios per face region,
   not a trained classifier. The `occluded_ratio` on a record is indicative, not reliable.
5. **A wrong `absent` is the costliest error**, so the rules never produce one from weak
   evidence — unconfirmed sightings become `needs_review` for a human. This is a design choice
   that trades faculty time for fairness, and it should not be tuned away.
