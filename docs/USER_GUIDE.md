# Attendance portal — user guide

The same guide is on the website at **/guide** (no sign-in needed), where the times and the
minimum percentage are your college's actual settings. The defaults are shown here.

## Students

1. **Register.** Open **/signup**. Fill in your details exactly as in college records, choose
   your branch, year, batch and section, and add a clear profile photo. Enter the 6-digit code
   sent to your email.
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
branch, employee ID and whether you are a teacher or HOD. Confirm your email with the code we
send; the account works once an administrator approves it (an HOD can approve teachers of their
own branch; HOD rights are granted by the super admin only).

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
4. **Cameras.** Classroom cameras mark students they are confident about. Uncertain matches wait
   in **Camera review** with the face crop next to the profile photo — accept or reject. You are
   notified if a camera goes offline during your lecture.
5. **Leave, issues, messages, notices.** Approve or reject leave (approving it also corrects
   absences already recorded for those days), answer issues, message one student, a class, or
   all your students, and post notices with optional email.
6. **Reports.** Daily, monthly, subject-wise, student-wise and defaulter reports for any date
   range, each downloadable as CSV, Excel or PDF.

## Administrators and HODs

Everything teachers can do, for your department (HOD) or the whole college (super admin), plus
**Academic setup**, **Staff & roles** and **CCTV cameras**. Only the super admin can change
**Settings** (teachers can read them) and open the **Audit log**, which records every
attendance change, approval and permission change with who did it and when.
Installation and configuration: see [DEPLOY.md](DEPLOY.md).
