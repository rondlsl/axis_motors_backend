import styles from "./styles.module.scss";
import { IProps } from "./props";

export const BannerTitle = ({ title }: IProps) => {
  return <span className={styles.content}>{title}</span>;
};
