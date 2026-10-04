import { SignIn } from "@/components/sign-in";

export const metadata = { title: "Authority sign in" };

export default function AuthorityLoginPage() {
  return <SignIn portal="authority" />;
}
