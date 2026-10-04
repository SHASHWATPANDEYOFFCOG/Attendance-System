# Attendance portal — user guide

The same guide is on the website at **/guide** (no sign-in needed), where the times and the
minimum percentage are your college's actual settings. The defaults are shown here.

## Students

1. **Register.** Open **/signup**. Fill in your details exactly as in college records, choose
   your branch, year, batch and section, and add a clear profile photo. Then sign in. (If your
   college has switched on email codes, enter the 6-digit code we email you first.)
2. **Wait for approval.** Your class teacher checks and approves your account. You can sign in
   meanwhile, but cannot mark attendance until approved. If you are rejected, the reason is
   shown: fix your details under **My profile** and resubmit.
3. **Enrol your face (optional, needed for face check and classroom cameras).** Open
   **Face check**, read and accept the consent, then follow the prompts: look straight, then turn
   and tilt your head slightly as asked. Use good light; no mask or sunglasses. A teacher
   approves it. You can withdraw consent at any time, which deletes your face data.
4. **Mark attendance in class.** When a lecture is live, **Mark attendance** appears on your
   dashboard. Choose **Face check** (a short selfie with head turns) or **Classroom code** (scan
   the QR on the classroom screen or type its 6 digits). Your location is checked once.
   - within **10 minutes** of the start: **Present**
   - up to **20 minutes**: **Late**
   - after that the window is closed; anyone not marked when the lecture ends is **Absent**

   Classroom cameras may also mark you automatically.
5. **Leave, issues, messages.** Apply for leave under **Leave** (attach a certificate if you
   have one). Approved leave shows as **On leave** and does not count against you. Ask for an
   attendance correction or report any other problem under **Issues**. Teachers' messages and
   notices are under **Messages**; the bell shows new notifications as they arrive.
6. **Stay above the minimum (75%).** Your dashboard shows your percentage overall and per
   subject, a calendar, how many classes you can still miss, and — if you are below — how many
   classes in a row you need. **History** downloads your full record as a PDF.

**Camera or location blocked?**
- Android (Chrome): tap the lock icon next to the address → Permissions → allow Camera and
  Location.
- iPhone (Safari): tap **aA** → Website Settings → allow Camera and Location; also check
  Settings → Privacy & Security → Location Services is on.

The portal can be installed like an app: browser menu → **Add to Home screen** /
**Install app**.

## Teachers

Sign in at **/authority/login** (students use **/login**). You land on the authority dashboard.

No account yet? Use **Register** on the authority sign-in page (**/authority/register**): your
branch, employee ID and whether you are a teacher or HOD. By default you can sign in straight
away with teacher access; HOD rights are granted by the super admin. (Colleges can switch on an
email code and/or administrator approval under Settings.)

1. **Your classes.** The admin or HOD assigns your subjects and classes and builds the
   timetable. Everywhere — directory, reports, leave, issues — you see only students of your
   classes.
2. **Approvals.** Lists new registrations (check them against college records), profile
   corrections, and face enrolments (compare the photos with the profile photo). A rejection
   always needs a reason, which the student sees.
3. **Running a lecture.** Lectures start by themselves at the timetabled time, or press
   **Start session** in **Live sessions**. Open **Show QR full-screen** on the classroom
   projector. The live list fills in as students mark; tap **P / L / A / O / E** to mark anyone
   by hand. Changing a mark that is already recorded asks for a reason, which is logged and sent
   to the student. At the end time everyone unmarked becomes Absent (or On leave, if covered by
   approved leave).
4. **Tablet photo and cameras.** On a live lecture's page:
   - **Tablet photo** — photograph the class with a tablet or phone (**Open camera**, or the
     device's own camera app). Recognised students are ticked for you; untick anyone who is not
     there, tick "check" suggestions you are sure of, then **Mark … as here**. Take two or three
     photos for a large room. Photos are never saved; unrecognised faces are not identified.
   - **Classroom camera** — connect any registered CCTV camera to the lecture (useful when the
     room's own camera is missing or a spare one covers the class better), **Check the view**,
     and disconnect when done. A connected camera marks students it is confident about by itself
     and stops when the lecture ends.

   Uncertain camera matches wait in **Camera review** with the face crop next to the profile
   photo — accept or reject. You are notified if a camera goes offline during your lecture.
5. **Leave, issues, messages, notices.** Approve or reject leave (approving it also corrects
   absences already recorded for those days), answer issues, message one student, a class, or
   all your students, and post notices with optional email.
6. **Reports.** Daily, monthly, subject-wise, student-wise and defaulter reports for any date
   range, each downloadable as CSV, Excel or PDF.

## Approval management (all authorities)

**Approvals → Students** lists students by status — **Pending, Approved, Rejected, Revoked** —
and filters by academic year, branch, batch, year and section. Approve, reject (with a reason),
revoke (the student keeps their record but cannot mark attendance) or restore, one at a time or
by ticking several. Every decision is recorded in the audit log with the old and new status.

## Tablets (all authorities)

1. **Tablets → Register a tablet**: name, workspace, and the cameras it may use. A one-time
   8-character pairing code appears (valid 15 minutes).
2. On the tablet: open the site, sign in at **/authority/login**, go to **Tablets**, and enter the
   code under **This device**.
3. The tablet can now take **Tablet photo** attendance and control its cameras on a live
   lecture. **Disable** it temporarily, **Re-pair** to replace the device, or **Revoke** a lost one.

## Administrators

Administrators control everything: **Academic setup** (academic years, branches, batches,
sections — each can be deactivated), **Workspaces**, **CCTV cameras**, **Staff & roles**,
**Settings** (including **Access codes**) and the **Audit log**. An authority becomes an
administrator by entering the administrator code under **Administration → Administrator
access**. HODs manage the academic data of their own branch.
Installation and configuration: see [DEPLOY.md](DEPLOY.md).
