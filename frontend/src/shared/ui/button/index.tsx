import styles from "./styles.module.scss";
import { IProps } from "./props";
import { PropsWithChildren } from "react";
import classNames from "classnames";

export const Button = (props: PropsWithChildren<IProps>) => {
  const {
    children,
    size = "sm",
    mode = "primary",
    disabled,
    className,
    onClick,
    type,
    uppercase = true,
    ...otherProps
  } = props;

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={classNames(
        styles.button,
        styles[mode],
        styles[size],
        className,
      )}
      {...otherProps}
    >
      {children}
    </button>
  );
};
