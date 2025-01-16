"use client";

import styles from "./styles.module.scss";
import { IProps } from "./props";
import Image from "next/image";
import { useState } from "react";
import classNames from "classnames";

export const CarDetailsImges = (props: IProps) => {
  const [activeImg, setActiveImg] = useState(1);

  const handleActiveImgChange = (index: number) => {
    setActiveImg(index);
  };

  const checkActive = (index: number) => {
    return activeImg === index;
  };

  return (
    <section className={styles.content}>
      <div className={styles.main}>
        <Image
          src={`/img/common/view-${activeImg}.jpg`}
          alt={"View"}
          width={492}
          height={360}
        />
      </div>
      <div className={styles.bottom}>
        <button
          className={classNames(
            styles.secondary,
            checkActive(1) && styles.active,
          )}
          onClick={() => handleActiveImgChange(1)}
        >
          <Image
            src={"/img/common/view-1.jpg"}
            alt={"View"}
            width={148}
            height={124}
          />
        </button>
        <button
          className={classNames(
            styles.secondary,
            checkActive(2) && styles.active,
          )}
          onClick={() => handleActiveImgChange(2)}
        >
          <Image
            src={"/img/common/view-2.jpg"}
            alt={"View"}
            width={148}
            height={124}
          />
        </button>
        <button
          className={classNames(
            styles.secondary,
            checkActive(3) && styles.active,
          )}
          onClick={() => handleActiveImgChange(3)}
        >
          <Image
            src={"/img/common/view-3.jpg"}
            alt={"View"}
            width={148}
            height={124}
          />
        </button>
      </div>
    </section>
  );
};
