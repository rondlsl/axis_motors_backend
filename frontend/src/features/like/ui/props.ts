import { ButtonHTMLAttributes, DetailedHTMLProps } from "react";

export interface IProps
  extends DetailedHTMLProps<
    ButtonHTMLAttributes<HTMLButtonElement>,
    HTMLButtonElement
  > {
  liked: boolean | undefined;
  carId: string;
  onLike: (id: string) => void;
}
