import styles from "./styles.module.scss";
import { IProps } from "./props";
import classNames from "classnames";

export const PickDrop = ({ title, date, time, city, dataChange }: IProps) => {
  return (
    <div className={classNames("bg-bgSecondary", styles.content, "space-y-2")}>
      <div className={styles.top}>{title}</div>
      <div className={styles.bottom}>
        <div className={styles.info}>
          <p>Location</p>
          <select
            value={city}
            onChange={(e) => dataChange("city", e.target.value)}
          >
            <option value="Almaty">Almaty</option>
            <option value="Astana">Astana</option>
            <option value="Atyrau">Atyrau</option>
            <option value="Aktobe">Aktobe</option>
            <option value="Aktau">Aktau</option>
            <option value="Shymkent">Shymkent</option>
            <option value="Uralsk">Uralsk</option>
            <option value="Kostanay">Kostanay</option>
            <option value="Pavlodar">Pavlodar</option>
          </select>
        </div>
        <div className={styles.line} />
        <div className={styles.info}>
          <p>Date</p>
          <input
            type="date"
            value={date}
            onChange={(e) => dataChange("date", e.target.value)}
          />
        </div>
        <div className={styles.line} />
        <div className={styles.info}>
          <p>Time</p>
          <input
            type="time"
            value={time}
            onChange={(e) => dataChange("time", e.target.value)}
          />
        </div>
      </div>
    </div>
  );
};
