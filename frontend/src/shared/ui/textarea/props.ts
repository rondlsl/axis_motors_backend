import { DetailedHTMLProps, TextareaHTMLAttributes } from "react";

export interface IProps
  extends DetailedHTMLProps<
    TextareaHTMLAttributes<HTMLTextAreaElement>,
    HTMLTextAreaElement
  > {}
