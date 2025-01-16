import styles from "./styles.module.scss";
import { IProps } from "./props";

export const PageTitle = ({ title, subTitle }: IProps) => {
  return (
    <div className={styles.content}>
      <h3 className={styles.title}>{title}</h3>
      <p className={styles.subTitle}>{subTitle}</p>
    </div>
  );
};
