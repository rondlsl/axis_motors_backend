import { ButtonHTMLAttributes, DetailedHTMLProps } from "react";
import { ButtonMode, ButtonSize } from "shared/common";

export interface IProps
  extends DetailedHTMLProps<
    ButtonHTMLAttributes<HTMLButtonElement>,
    HTMLButtonElement
  > {
  size?: ButtonSize;
  mode?: ButtonMode;
  uppercase?: boolean;
}
