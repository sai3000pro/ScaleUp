"""Small score assets used by the zero-provider instrument demos."""

PIANO_STEPWISE_SCORE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Stepwise C Major</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
    </measure>
  </part>
</score-partwise>
"""

GUITAR_LOW_E_FRETTING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Low E Fretting Drill</work-title></work>
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type></direction>
      <note><pitch><step>E</step><octave>2</octave></pitch><duration>1</duration><voice>1</voice><notations><technical><string>6</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>F</step><octave>2</octave></pitch><duration>1</duration><voice>1</voice><notations><technical><string>6</string><fret>1</fret></technical></notations></note>
      <note><pitch><step>G</step><octave>2</octave></pitch><duration>1</duration><voice>1</voice><notations><technical><string>6</string><fret>3</fret></technical></notations></note>
      <note><pitch><step>A</step><octave>2</octave></pitch><duration>1</duration><voice>1</voice><notations><technical><string>6</string><fret>5</fret></technical></notations></note>
    </measure>
  </part>
</score-partwise>
"""

VIOLIN_OPEN_STRINGS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Open String Scale</work-title></work>
  <part-list><score-part id="P1"><part-name>Violin</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type></direction>
      <note><pitch><step>G</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
      <note><pitch><step>A</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>1</duration><voice>1</voice></note>
    </measure>
  </part>
</score-partwise>
"""

TRUMPET_C_ARPEGGIO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>C Major Arpeggio</work-title></work>
  <part-list><score-part id="P1"><part-name>Trumpet</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration><voice>1</voice></note>
    </measure>
  </part>
</score-partwise>
"""

GUITAR_GCD_STRUM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>G C D Strum</work-title></work>
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type></direction>
      <note><pitch><step>G</step><octave>2</octave></pitch><duration>1</duration><voice>1</voice><notations><technical><string>6</string><fret>3</fret></technical></notations></note>
      <note><pitch><step>B</step><octave>2</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>5</string><fret>2</fret></technical></notations></note>
      <note><pitch><step>D</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>4</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>G</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>3</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>B</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>2</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>1</string><fret>3</fret></technical></notations></note>
      <note><pitch><step>C</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><notations><technical><string>5</string><fret>3</fret></technical></notations></note>
      <note><pitch><step>E</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>4</string><fret>2</fret></technical></notations></note>
      <note><pitch><step>G</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>3</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>2</string><fret>1</fret></technical></notations></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>1</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>D</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><notations><technical><string>4</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>A</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>3</string><fret>2</fret></technical></notations></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>2</string><fret>3</fret></technical></notations></note>
      <note><pitch><step>F</step><alter>1</alter><octave>4</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>1</string><fret>2</fret></technical></notations></note>
      <note><pitch><step>G</step><octave>2</octave></pitch><duration>1</duration><voice>1</voice><notations><technical><string>6</string><fret>3</fret></technical></notations></note>
      <note><pitch><step>B</step><octave>2</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>5</string><fret>2</fret></technical></notations></note>
      <note><pitch><step>D</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>4</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>G</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>3</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>B</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>2</string><fret>0</fret></technical></notations></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><chord/><notations><technical><string>1</string><fret>3</fret></technical></notations></note>
    </measure>
  </part>
</score-partwise>
"""

DRUMS_ROCK_GROOVE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Rock Groove</work-title></work>
  <part-list><score-part id="P1"><part-name>Drums</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>2</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>70</per-minute></metronome></direction-type></direction>
      <note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched><duration>1</duration><voice>1</voice></note>
      <note><unpitched><display-step>F#</display-step><display-octave>5</display-octave></unpitched><duration>1</duration><voice>1</voice></note>
      <note><unpitched><display-step>D</display-step><display-octave>5</display-octave></unpitched><duration>1</duration><voice>1</voice></note>
      <note><unpitched><display-step>F#</display-step><display-octave>5</display-octave></unpitched><duration>1</duration><voice>1</voice></note>
      <note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched><duration>1</duration><voice>1</voice></note>
      <note><unpitched><display-step>F#</display-step><display-octave>5</display-octave></unpitched><duration>1</duration><voice>1</voice></note>
      <note><unpitched><display-step>D</display-step><display-octave>5</display-octave></unpitched><duration>1</duration><voice>1</voice></note>
      <note><unpitched><display-step>F#</display-step><display-octave>5</display-octave></unpitched><duration>1</duration><voice>1</voice></note>
    </measure>
  </part>
</score-partwise>
"""
