import styles from "./styles.module.scss";
import { IProps } from "./props";
import classNames from "classnames";
import Image from "next/image";

export const Like = (props: IProps) => {
  const {
    liked,
    onLike,
    carId,
    disabled,
    className,
    onClick,
    type,
    ...otherProps
  } = props;
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={() => onLike(carId)}
      className={classNames(styles.button, className)}
      {...otherProps}
    >
      {liked ? (
        <Image
          width={24}
          height={24}
          src="/img/utils/heart-fill.svg"
          alt="Heart Fill"
        />
      ) : (
        <Image
          width={24}
          height={24}
          src="/img/utils/heart-outline.svg"
          alt="Heart Outline"
        />
      )}
    </button>
  );
};
