import { SignIn } from "@/components/sign-in";

export const metadata = { title: "Student sign in" };

export default function StudentLoginPage() {
  return <SignIn portal="student" />;
}
