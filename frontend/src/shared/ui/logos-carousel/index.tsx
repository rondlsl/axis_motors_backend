import styles from "./styles.module.scss";
import { IProps } from "./props";
import Image from "next/image";

const logos = [
  { src: "/img/utils/honda.svg", alt: "Honda", width: 273, height: 67 },
  { src: "/img/utils/acura.svg", alt: "Acura", width: 215, height: 50 },
  { src: "/img/utils/audi.svg", alt: "Audi", width: 144, height: 51 },
  { src: "/img/utils/jaguar.svg", alt: "Jaguar", width: 225, height: 19 },
  { src: "/img/utils/nissan.svg", alt: "Nissan", width: 80, height: 67 },
  { src: "/img/utils/volvo.svg", alt: "Volvo", width: 225, height: 18 },
];

export const LogosCarousel = (props: IProps) => {
  return (
    <div className={styles.content}>
      <div className={styles.slidTrack}>
        {logos.map((logo, index) => (
          <div className={styles.logos} key={index}>
            <Image
              src={logo.src}
              alt={logo.alt}
              width={logo.width}
              height={logo.height}
            />
          </div>
        ))}
        {logos.map((logo, index) => (
          <div className={styles.logos} key={index + logos.length}>
            <Image
              src={logo.src}
              alt={logo.alt}
              width={logo.width}
              height={logo.height}
            />
          </div>
        ))}
        {logos.map((logo, index) => (
          <div className={styles.logos} key={index + logos.length}>
            <Image
              src={logo.src}
              alt={logo.alt}
              width={logo.width}
              height={logo.height}
            />
          </div>
        ))}
        {logos.map((logo, index) => (
          <div className={styles.logos} key={index + logos.length}>
            <Image
              src={logo.src}
              alt={logo.alt}
              width={logo.width}
              height={logo.height}
            />
          </div>
        ))}
        {logos.map((logo, index) => (
          <div className={styles.logos} key={index + logos.length}>
            <Image
              src={logo.src}
              alt={logo.alt}
              width={logo.width}
              height={logo.height}
            />
          </div>
        ))}
      </div>
    </div>
  );
};
