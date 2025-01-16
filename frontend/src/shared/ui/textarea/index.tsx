import styles from "./styles.module.scss";
import { IProps } from "./props";
import classNames from "classnames";

export const Textarea = ({
  value,
  onChange,
  placeholder,
  className,
  ...otherProps
}: IProps) => {
  return (
    <textarea
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      className={classNames(styles.content, className)}
      {...otherProps}
    />
  );
};
