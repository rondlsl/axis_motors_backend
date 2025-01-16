import styles from "./styles.module.scss";
import { IProps } from "./props";
import Image from "next/image";

export const CardReview = ({ review, pfp, city, fullName }: IProps) => {
  return (
    <div className={styles.content}>
      <p className={styles.review}>{review}</p>
      <div className={styles.bottom}>
        <div className={styles.info}>
          <div className={styles.pfp}>
            <Image src={pfp} alt={"User Pfp"} width={100} height={100} />
          </div>
          <div className={styles.more}>
            <p className={styles.name}>{fullName}</p>
            <p className={styles.city}>{city}</p>
          </div>
        </div>
        <span className={styles.quoteIcon}>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="60"
            height="60"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--clr-primary)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="tabler-icon tabler-icon-quote"
          >
            <path d="M10 11h-4a1 1 0 0 1 -1 -1v-3a1 1 0 0 1 1 -1h3a1 1 0 0 1 1 1v6c0 2.667 -1.333 4.333 -4 5"></path>
            <path d="M19 11h-4a1 1 0 0 1 -1 -1v-3a1 1 0 0 1 1 -1h3a1 1 0 0 1 1 1v6c0 2.667 -1.333 4.333 -4 5"></path>
          </svg>
        </span>
      </div>
    </div>
  );
};
