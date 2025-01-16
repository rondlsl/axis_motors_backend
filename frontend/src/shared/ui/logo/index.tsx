import Link from "next/link";
import { IProps } from "./props";

export const Logo = ({ mode = "primary" }: IProps) => {
  return (
    <Link
      href={"/"}
      className={`text-3xl font-semibold ${mode === "primary" ? "text-primary" : "text-white"}`}
    >
      Azv Motors
    </Link>
  );
};
